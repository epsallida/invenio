# -*- coding: utf-8 -*-
##
## This file is part of Invenio.
## Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2013 CERN.
##
## Invenio is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## Invenio is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Invenio; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

from __future__ import print_function

""" Error handling library """

__revision__ = "$Id$"

import traceback
import os
import sys
import time
import datetime
import re
import inspect
from flask import current_app
from six import iteritems, StringIO

from invenio.base.globals import cfg
from .models import HstEXCEPTION


## Regular expression to match possible password related variable that should
## be disclosed in frame analysis.
RE_PWD = re.compile(r"pwd|pass|p_pw", re.I)


def get_pretty_wide_client_info(req):
    """Return in a pretty way all the avilable information about the current
    user/client"""
    if req:
        from invenio.legacy.webuser import collect_user_info
        user_info = collect_user_info(req)
        keys = user_info.keys()
        keys.sort()
        max_key = max([len(key) for key in keys])
        ret = ""
        fmt = "%% %is: %%s\n" % max_key
        for key in keys:
            if RE_PWD.search(key):
                continue
            if key in ('uri', 'referer'):
                ret += fmt % (key, "<%s>" % user_info[key])
            else:
                ret += fmt % (key, user_info[key])
        if ret.endswith('\n'):
            return ret[:-1]
        else:
            return ret
    else:
        return "No client information available"


def get_tracestack():
    """
    If an exception has been caught, return the system tracestack or else
    return tracestack of what is currently in the stack
    """
    if traceback.format_tb(sys.exc_info()[2]):
        delimiter = "\n"
        tracestack_pretty = "Traceback: \n%s" % \
            delimiter.join(traceback.format_tb(sys.exc_info()[2]))
    else:
        ## force traceback except for this call
        tracestack = traceback.extract_stack()[:-1]
        tracestack_pretty = "%sForced traceback (most recent call last)" % \
                            (' '*4, )
        for trace_tuple in tracestack:
            tracestack_pretty += """
    File "%(file)s", line %(line)s, in %(function)s
        %(text)s""" % {
            'file': trace_tuple[0],
            'line': trace_tuple[1],
            'function': trace_tuple[2],
            'text': trace_tuple[3] is not None and \
                    str(trace_tuple[3]) or ""}
    return tracestack_pretty


def register_emergency(msg, recipients=None):
    """Launch an emergency. This means to send email messages to each
    address in 'recipients'. By default recipients will be obtained via
    get_emergency_recipients() which loads settings from
    CFG_SITE_EMERGENCY_EMAIL_ADDRESSES
    """
    from invenio.ext.email import send_email
    if not recipients:
        recipients = get_emergency_recipients()
    recipients = set(recipients)
    recipients.add(cfg['CFG_SITE_ADMIN_EMAIL'])
    for address_str in recipients:
        send_email(cfg['CFG_SITE_SUPPORT_EMAIL'], address_str, "Emergency notification", msg)


def get_emergency_recipients(recipient_cfg=None):
    """Parse a list of appropriate emergency email recipients from
    CFG_SITE_EMERGENCY_EMAIL_ADDRESSES, or from a provided dictionary
    comprised of 'time constraint' => 'comma separated list of addresses'

    CFG_SITE_EMERGENCY_EMAIL_ADDRESSES format example:

    CFG_SITE_EMERGENCY_EMAIL_ADDRESSES = {
        'Sunday 22:00-06:00': '0041761111111@email2sms.foo.com',
        '06:00-18:00': 'team-in-europe@foo.com,0041762222222@email2sms.foo.com',
        '18:00-06:00': 'team-in-usa@foo.com',
        '*': 'john.doe.phone@foo.com'}
    """

    from invenio.utils.date import parse_runtime_limit
    if recipient_cfg is None:
        recipient_cfg = cfg['CFG_SITE_EMERGENCY_EMAIL_ADDRESSES']

    recipients = set()
    for time_condition, address_str in recipient_cfg.items():
        if time_condition and time_condition is not '*':
            (current_range, future_range) = parse_runtime_limit(time_condition)
            if not current_range[0] <= datetime.datetime.now() <= current_range[1]:
                continue

        recipients.update([address_str])
    return list(recipients)


def find_all_values_to_hide(local_variables, analyzed_stack=None):
    """Return all the potential password to hyde."""
    ## Let's add at least the DB password.
    if analyzed_stack is None:
        ret = set([cfg['CFG_DATABASE_PASS']])
        analyzed_stack = set()
    else:
        ret = set()
    for key, value in iteritems(local_variables):
        if id(value) in analyzed_stack:
            ## Let's avoid loops
            continue
        analyzed_stack.add(id(value))
        if RE_PWD.search(key):
            ret.add(str(value))
        if isinstance(value, dict):
            ret |= find_all_values_to_hide(value, analyzed_stack)
    if '' in ret:
        ## Let's discard the empty string in case there is an empty password,
        ## or otherwise anything will be separated by '<*****>' in the output
        ## :-)
        ret.remove('')
    return ret


def get_pretty_traceback(req=None, exc_info=None, skip_frames=0):
    """
    Given an optional request object and an optional exc_info,
    returns a text string representing many details about an exception.
    """
    if exc_info is None:
        exc_info = sys.exc_info()
    if exc_info[0]:
        ## We found an exception.

        ## We want to extract the name of the Exception
        exc_name = exc_info[0].__name__
        exc_value = str(exc_info[1])
        filename, line_no, function_name = _get_filename_and_line(exc_info)

        ## Let's record when and where and what
        www_data = "%(time)s -> %(name)s: %(value)s (%(file)s:%(line)s:%(function)s)" % {
            'time': time.strftime("%Y-%m-%d %H:%M:%S"),
            'name': exc_name,
            'value': exc_value,
            'file': filename,
            'line': line_no,
            'function': function_name }

        ## Let's retrieve contextual user related info, if any
        try:
            client_data = get_pretty_wide_client_info(req)
        except Exception as err:
            client_data = "Error in retrieving " \
                "contextual information: %s" % err

        ## Let's extract the traceback:
        tracestack_data_stream = StringIO()
        print("\n** Traceback details \n", file=tracestack_data_stream)
        traceback.print_exc(file=tracestack_data_stream)
        stack = [frame[0] for frame in inspect.trace()]
        #stack = [frame[0] for frame in inspect.getouterframes(exc_info[2])][skip_frames:]
        try:
            stack.reverse()
            print("\n** Stack frame details", file=tracestack_data_stream)
            values_to_hide = set()
            for frame in stack:
                try:
                    print(file=tracestack_data_stream)
                    print("Frame %s in %s at line %s" % (
                                frame.f_code.co_name,
                                frame.f_code.co_filename,
                                frame.f_lineno), file=tracestack_data_stream)
                    ## Dereferencing f_locals
                    ## See: http://utcc.utoronto.ca/~cks/space/blog/python/FLocalsAndTraceFunctions
                    local_values = frame.f_locals
                    try:
                        values_to_hide |= find_all_values_to_hide(local_values)

                        code = open(frame.f_code.co_filename).readlines()
                        first_line = max(1, frame.f_lineno-3)
                        last_line = min(len(code), frame.f_lineno+3)
                        print("-" * 79, file=tracestack_data_stream)
                        for line in xrange(first_line, last_line+1):
                            code_line = code[line-1].rstrip()
                            if line == frame.f_lineno:
                                print("----> %4i %s" % (line, code_line), file=tracestack_data_stream)
                            else:
                                print("      %4i %s" % (line, code_line), file=tracestack_data_stream)
                        print("-" * 79, file=tracestack_data_stream)
                    except:
                        pass
                    for key, value in local_values.items():
                        print("\t%20s = " % key, end=' ', file=tracestack_data_stream)
                        try:
                            value = repr(value)
                        except Exception as err:
                            ## We shall gracefully accept errors when repr() of
                            ## a value fails (e.g. when we are trying to repr() a
                            ## variable that was not fully initialized as the
                            ## exception was raised during its __init__ call).
                            value = "ERROR: when representing the value: %s" % (err)
                        try:
                            print(_truncate_dynamic_string(value), file=tracestack_data_stream)
                        except:
                            print("<ERROR WHILE PRINTING VALUE>", file=tracestack_data_stream)
                finally:
                    del frame
        finally:
            del stack
        tracestack_data = tracestack_data_stream.getvalue()
        for to_hide in values_to_hide:
            ## Let's hide passwords
            tracestack_data = tracestack_data.replace(to_hide, '<*****>')

        ## Okay, start printing:
        output = StringIO()

        print("* %s" % www_data, file=output)
        print("\n** User details", file=output)
        print(client_data, file=output)

        if tracestack_data:
            print(tracestack_data, file=output)
        return output.getvalue()
    else:
        return ""


def register_exception(stream='error',
                       req=None,
                       prefix='',
                       suffix='',
                       alert_admin=False,
                       subject=''):
    """
    Log error exception to invenio.err and warning exception to invenio.log.
    Errors will be logged together with client information (if req is
    given).

    Note:   For sanity reasons, dynamic params such as PREFIX, SUFFIX and
            local stack variables are checked for length, and only first 500
            chars of their values are printed.

    @param stream: 'error' or 'warning'

    @param req: mod_python request

    @param prefix: a message to be printed before the exception in
    the log

    @param suffix: a message to be printed before the exception in
    the log

    @param alert_admin: wethever to send the exception to the administrator via
        email. Note this parameter is bypassed when
                CFG_SITE_ADMIN_EMAIL_EXCEPTIONS is set to a value different than 1
    @param subject: overrides the email subject

    @return: 1 if successfully wrote to stream, 0 if not
    """


    try:
        ## Let's extract exception information
        exc_info = sys.exc_info()
        exc_name = exc_info[0].__name__
        output = get_pretty_traceback(
            req=req, exc_info=exc_info, skip_frames=2)
        if output:
            ## Okay, start printing:
            log_stream = StringIO()
            email_stream = StringIO()

            print('\n', end=' ', file=email_stream)

            ## If a prefix was requested let's print it
            if prefix:
                #prefix = _truncate_dynamic_string(prefix)
                print(prefix + '\n', file=log_stream)
                print(prefix + '\n', file=email_stream)

            print(output, file=log_stream)
            print(output, file=email_stream)

            ## If a suffix was requested let's print it
            if suffix:
                #suffix = _truncate_dynamic_string(suffix)
                print(suffix, file=log_stream)
                print(suffix, file=email_stream)

            log_text = log_stream.getvalue()
            email_text = email_stream.getvalue()

            if email_text.endswith('\n'):
                email_text = email_text[:-1]

            ## Preparing the exception dump
            if stream=='error':
                logger_method = current_app.logger.error
            else:
                logger_method = current_app.logger.info

            ## We now have the whole trace
            written_to_log = False
            try:
                ## Let's try to write into the log.
                logger_method(log_text)
                written_to_log = True
            except:
                written_to_log = False
            filename, line_no, function_name = _get_filename_and_line(exc_info)

            ## let's log the exception and see whether we should report it.
            log = HstEXCEPTION.get_or_create(exc_name, filename, line_no)
            if log.exception_should_be_notified and (
                    cfg['CFG_SITE_ADMIN_EMAIL_EXCEPTIONS'] > 1 or
                    (alert_admin and
                     cfg['CFG_SITE_ADMIN_EMAIL_EXCEPTIONS'] > 0) or
                    not written_to_log):
                ## If requested or if it's impossible to write in the log
                from invenio.ext.email import send_email
                if not subject:
                    subject = 'Exception (%s:%s:%s)' % (
                        filename, line_no, function_name)
                subject = '%s at %s' % (subject, cfg['CFG_SITE_URL'])
                email_text = "\n%s\n%s" % (log.pretty_notification_info,
                                           email_text)
                if not written_to_log:
                    email_text += """\
Note that this email was sent to you because it has been impossible to log
this exception into %s""" % os.path.join(cfg['CFG_LOGDIR'], 'invenio.' + stream)
                send_email(
                    cfg['CFG_SITE_ADMIN_EMAIL'],
                    cfg['CFG_SITE_ADMIN_EMAIL'],
                    subject=subject,
                    content=email_text)
            return 1
        else:
            return 0
    except Exception as err:
        print("Error in registering exception to '%s': '%s'" % (
            cfg['CFG_LOGDIR'] + '/invenio.' + stream, err), file=sys.stderr)
        return 0


def raise_exception(exception_type=Exception, msg='', stream='error',
                    req=None, prefix='', suffix='', alert_admin=False,
                    subject=''):
    """
    Log error exception to invenio.err and warning exception to invenio.log.
    Errors will be logged together with client information (if req is
    given).

    It does not require a previously risen exception.

    Note:   For sanity reasons, dynamic params such as PREFIX, SUFFIX and
            local stack variables are checked for length, and only first 500
            chars of their values are printed.

    @param exception_type: exception type to be used internally

    @param msg: error message

    @param stream: 'error' or 'warning'

    @param req: mod_python request

    @param prefix: a message to be printed before the exception in
    the log

    @param suffix: a message to be printed before the exception in
    the log

    @param alert_admin: wethever to send the exception to the administrator via
        email. Note this parameter is bypassed when
               CFG_SITE_ADMIN_EMAIL_EXCEPTIONS is set to a value different than 1
    @param subject: overrides the email subject

    @return: 1 if successfully wrote to stream, 0 if not
    """
    try:
        raise exception_type(msg)
    except:
        return register_exception(stream=stream,
                                  req=req,
                                  prefix=prefix,
                                  suffix=suffix,
                                  alert_admin=alert_admin,
                                  subject=subject)


def send_error_report_to_admin(header, url, time_msg,
                               browser, client, error,
                               sys_error, traceback_msg):
    """
    Sends an email to the admin with client info and tracestack
    """
    from_addr = '%s Alert Engine <%s>' % (
        cfg['CFG_SITE_NAME'], cfg['CFG_WEBALERT_ALERT_ENGINE_EMAIL'])
    to_addr = cfg['CFG_SITE_ADMIN_EMAIL']
    body = """
The following error was seen by a user and sent to you.
%(contact)s

%(header)s

%(url)s
%(time)s
%(browser)s
%(client)s
%(error)s
%(sys_error)s
%(traceback)s

Please see the %(logdir)s/invenio.err for traceback details.""" % {
        'header': header,
        'url': url,
        'time': time_msg,
        'browser': browser,
        'client': client,
        'error': error,
        'sys_error': sys_error,
        'traceback': traceback_msg,
        'logdir': cfg['CFG_LOGDIR'],
        'contact': "Please contact %s quoting the following information:" %
            (cfg['CFG_SITE_SUPPORT_EMAIL'], )}
    from invenio.ext.email import send_email
    send_email(from_addr, to_addr, subject="Error notification", content=body)


def _get_filename_and_line(exc_info):
    """Return the filename, the line and the function_name where
    the exception happened."""
    tb = exc_info[2]
    exception_info = traceback.extract_tb(tb)[-1]
    filename = os.path.basename(exception_info[0])
    line_no = exception_info[1]
    function_name = exception_info[2]
    return filename, line_no, function_name


def _truncate_dynamic_string(val, maxlength=500):
    """
    Return at most MAXLENGTH characters of VAL.  Useful for
    sanitizing dynamic variable values in the output.
    """
    out = repr(val)
    if len(out) > maxlength:
        out = out[:maxlength] + ' [...]'
    return out


def wrap_warn():
    import warnings
    from functools import wraps

    def wrapper(showwarning):
        @wraps(showwarning)
        def new_showwarning(message=None, category=None, filename=None,
                            lineno=None, file=None, line=None):
            current_app.logger.warning("* %(time)s -> WARNING: %(category)s: %(message)s (%(file)s:%(line)s)\n" % {
                'time': time.strftime("%Y-%m-%d %H:%M:%S"),
                'category': category,
                'message': message,
                'file': filename,
                'line': lineno} + "** Traceback details\n" +
                str(traceback.format_stack()) + "\n")
        return new_showwarning

    warnings.showwarning = wrapper(warnings.showwarning)