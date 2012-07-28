#-*- coding: UTF-8 -*-

from txtorcon import torcontrolprotocol
from cyclone import web
from cyclone.escape import json_encode, json_decode

import apaf
from apaf import config

class PanelHandler(web.RequestHandler):
    """
    A simple RequestHandler with utils for the panel
    """

    def initialize(self, action=None):
        self.action = action

    def error(self, msg):
        """
        Performs JSON response:
         * {"error" : error message }

        :param msg: error message
        """
        return json_encode({'error': str(msg)})

    def result(self, boolean):
        """
        Performs JSON response:
         * {"result" : true}
         * {"result": false}
        :param boolean: the boolean to be returned
        """
        return json_encode({'result':boolean})

    def get_current_user(self, passwd=None):
        """
        Return the current user authenticated.
        """
        if passwd: return passwd == config.custom['passwd']
        else: return any((
            self.get_secure_cookie('user') == config.custom['passwd'],
            self.request.remote_ip == '127.0.0.1',
        ))

    def set_default_headers(self):
        """
        Panel API is performed entirely via json calls.
        """
        self.set_header('Content-Type', 'application/json')


class IndexHandler(PanelHandler):
    def get(self):
        """
        Process GET request:
            * /
        """
        self.set_header('Content-Type', 'text/plain')
        self.finish('Hello world')

def render(page, _handler_name=None, **args):
    """
    Simple helper function for returning a web.RequestHandler page.
    :param page: path for html page
    :param _handler_name: classname for the handler (useful in debugging)
    :param args: arguments for html
    """
    def get(self):
        self.render(page, **args)

    return type(_handler_name or 'Handler_'+page,
                (web.RequestHandler, ),
                {'get': get})

class AuthHandler(PanelHandler):
    """
    Authentication:
        ** shall check if requests come from localhost?
        ** just oauth login?
        ***
    """
    _actions = ['login', 'logout']
    _uid_cookie = 'user'

    def initialize(self, action):
        if action not in self._actions:
            raise ValueError('Unexpected action')
        else:
            self.action = action

    def post(self):
        """
        Processes asyncronous request:
            * GET /auth/login
        """
        if self.action != 'login':
            raise web.HTTPError(404)

        # if self.request.remote_ip == '127.0.0.1':
        #     self.set_secure_cookie(self._uid_cookie, config.custom['passwd'])
        #     return self.write(self.result(True))

        if not config.custom['remote_login']:
            raise web.HTTPAuthenticationRequired

        request = json_decode(self.request.body)
        if 'passwd' not in request:
            return self.error('invalid request')
        elif not self.get_current_user(request['passwd']):
            return self.write(self.error('login failed'))
        else:
            self.set_secure_cookie('auth', self.request.body)
            return self.write(self.result(True))

    @web.authenticated
    def get(self):
        """
        Process asycnronous request:
            * GET /auth/logout
        """
        if self.action != 'logout':
            raise web.HTTPAuthenticationRequired if not self.current_user \
                  else web.HTTPError(404)

        #if not self.user:
        #    raise HTTPError(403)
        self.clear_cookie(self._uid_cookie)


class ConfigHandler(PanelHandler):
    """
    Controller for editing config.custom.
    """

    @web.authenticated
    def get(self):
        """
        Process GET requests:
            * /config
        Return a dictionary item:value for each item configurable from the
        panel.
        """
        ret = dict(config.custom)
        del ret['cookie_secret']
        del ret['passwd']
        return self.write(json_encode(ret))

    @web.authenticated
    def put(self):
        """
        Processes PUT requests:
            * /config
        """
        if not self.request.headers.get('Settings'):
            return self.error('invalid query')
        self._process(json_decode(self.request.headers['Settings']))

    @web.authenticated
    def post(self):
        """
        Processes POST requests:
            * /config

        <hellais> maker: sure. Though it's recommended to also create
                  the equivalent POST based method since certain browsers/HTTP
                  clients don't support PUT method
        """
        if not self.request.body:
            return self.error('invalid query')
        self._process(json_decode(self.request.body))


    def _process(self, settings):
        """
        Processes a dictionary key:value, and put it on the configuration file.
        """
        if not all(x in config.custom for x in settings):
            return self.write(self.error('invalid config file'))

        try:
            for key, value in settings.iteritems():
                config.custom[key] = value
            self.write(self.result(config.custom.commit()))
        except KeyError as err:
            self.write(self.error(err))
        except TypeError as err:
            self.write(self.error(err))


class ServiceHandler(PanelHandler):
    _actions = ['state', 'start', 'stop']

    @property
    def services(self):
        """
        Return a dictionary service-name:service-class of all instantiated
        services.
        """
        return {service.name:service for service in apaf.hiddenservices}

   # cache decorator here.
    def _get_service(self, name):
        if not name in self.services:
            raise web.HTTPError(404)
        else:
            return self.services[name]

    def state(self, service):
        """
        Process GET request:
            * /services/<service>/
        Return a dictionary containig a summary of what the service is and on
        which url is running on.
        """
        keys = ['name', 'desc', 'url']
        return {name:getattr(service, name, None) for name in keys}

    def start(self, service):
        """
        Process GET request:
            * /services/<service>/start
        """

    @web.asynchronous
    def stop(self, service):
        """
        Process GET request:
            * /services/<service>/stop
        """
        if service.name == 'panel':    # xxx. PanelService.name
            self.finish(self.result(False))

        stop = service.stop()
        if stop:
            stop.addCallback(self.finish, self.result(True))
        else:
            self.finish(self.result(True))

    @web.authenticated
    def get(self, service=None):
        """
        Processes GET requests:
          * /services/
          * /services/<service>/
          * /services/<service>/start
          * /services/<service>/stop
        """
        if not service:
            resp = json_encode(self.services.keys())
        elif self.action in self._actions:
            service = self._get_service(service)
            resp = getattr(self, self.action)(service)
        if resp:
            return self.finish(json_encode(resp))


class TorHandler(PanelHandler):
    """
    Return informations about the current tor status.
    """
    allowed = (
            'version', 'ns/all', 'status/bootstrap-phase',

    )

    @web.asynchronous
    @web.authenticated
    def get(self, sp_keyword='status/bootstrap-phase'):
        """
        Processes GET requests:
            * /tor/<sp_keyword>

        In case the GETINFO command returns a 552 error code, raise a 404.
        (controlspec.txt) «If some of the listed keywords can't be found,
        Tor replies with a "552 Unrecognized option" message.»

        In case tor is not yet started, return a error message in JSON format.
        """

        if not apaf.torctl:
            return self.finish(self.error('Tor is not started.'))
        if not sp_keyword in self.allowed:
            return self.finish(self.error('Invalid key %s') % sp_keyword)
        try:
            apaf.torctl.get_info(sp_keyword).addCallback(
                 lambda infos: self.finish(json_encode(infos)))
        except torcontrolprotocol.TorProtocolError as err:
            if err.code == 552:
                raise web.HTTPError(404)
            else:
                self.finish(self.error('%s (code %d)' % (err.text, err.code)))
