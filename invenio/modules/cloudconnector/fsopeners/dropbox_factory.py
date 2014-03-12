# -*- coding: utf-8 -*-
##
## This file is part of Invenio.
## Copyright (C) 2013 CERN.
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

"""A factory for dropbox file system"""

import dropbox

from fs.errors import ResourceNotFoundError

from invenio.base.globals import cfg
from invenio.ext.fs.cloudfs.dropboxfs import DropboxFS
from invenio.ext.sqlalchemy import db
from invenio.modules.accounts.models import User
from invenio.modules.cloudconnector.errors import CloudRedirectUrl, \
    ErrorBuildingFS

from flask import url_for
from invenio.modules.oauthclient.views.client import oauth
from invenio.modules.oauthclient.models import RemoteToken, RemoteAccount


class Factory(object):
    def build_fs(self, current_user, credentials, root=None,
                 callback_url=None, request=None, session=None):
        url = url_for('oauthclient.login', remote_app='dropbox')

        client_id = oauth.remote_apps['dropbox'].consumer_key
        user_id = current_user.get_id()
        token = RemoteToken.get(user_id, client_id)

        if token is not None:
            credentials = {'access_token': token.access_token}
            try:
                filesystem = DropboxFS(root, credentials)
                filesystem.about()
                return filesystem
            except ResourceNotFoundError, e:
                if(root != "/"):
                    filesystem = DropboxFS("/", credentials)
                filesystem.makedir(root, recursive=True)
                filesystem = DropboxFS(root, credentials)
                return filesystem
            except:
                raise CloudRedirectUrl(url, __name__)
        else:
            raise CloudRedirectUrl(url, __name__)

    def _update_cloudutils_settings(self, current_user, new_data):
        # Updates cloudutils settings in DataBase and refreshes current user
        user = User.query.get(current_user.get_id())

        client_id = oauth.remote_apps['dropbox'].consumer_key
        account = RemoteAccount.get(user.id, client_id)
        account.extra_data = new_data

        account.extra_data.update()
        db.session.commit()
        current_user.reload()
