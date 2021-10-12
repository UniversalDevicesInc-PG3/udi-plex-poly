#!/usr/bin/env python3
'''
A Simple UDI Poloyglot Controller to Listen for Plex Webhooks. 
'''
import udi_interface
from http.server import HTTPServer, BaseHTTPRequestHandler
from socket import socket,AF_INET,SOCK_DGRAM
from threading import Thread
from json import loads

# Grab Plex Client Def.
from .PlexClientNode import PlexClient

# Basic HTTP Listener Service
class PlexListener(BaseHTTPRequestHandler):

    def do_GET(self):
        # For Testing and Troubleshooting
        # Should see socket open to receive PLEX Webhooks. 
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'This service is only to receive Plex WebHooks')
        self.parent.logger.info('HTTP GET Recieved on {} from {}'.format(self.server.server_address,self.client_address))

    
    def do_POST(self):
        # Read in the POST message body in bytes
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length) 

        # Parse/Convert Body into Dict, looking for Plex JSON/event data only.
        payload = self.PlexJSONParse(body)

        # If not from Plex parser will return NONE, then ignore POST.
        if payload == None: 
            self.parent.warning('Non-Plex POST Recieved and Ignored.')
            return  
        
        # Call PlexControll.post_handler() passing the time and payload. 
        self.parent.post_handler(self.date_time_string(),payload)
        
    def PlexJSONParse(self,sBody):
        #########################################################
        # This function is a simple HTTP Post Request Parser.   #
        # If the POST includes JSON and contains a key "event"  #
        # then it assumes the POST is from a Plex Media Server. #
        # If Plex JSON/event returns a dict with the data.      # 
        # If NOT Plex JSON/event returns NONE.                  # 
        #########################################################
        try:
            # First ensure parameter was passed as a string. (In Not Convert)
            if not isinstance(sBody, str): sBody = sBody.decode("utf-8","ignore")
        except:
            return None

        # Parse sBody into a List with sep = '\r\n'
        RequestList = sBody.split('\r\n')

        # Loop through each line looking for 'Content-Type: application/json'
        # Once found it will look for JSON data with a key 'event'.
        bJSON = False
        for line in RequestList:
            if "Content-Type: application/json" in line: bJSON = True
            if "event" in line and bJSON == True:
                try:
                    return(loads(line))  # Return Plex Event JSON data as DICT.
                except:
                    return None
        return None # If Plex JSON/event is not found in HTTP Body.

# Main UDI Polyglot Controller
class PlexController(udi_interface.Node):

    def __init__(self, polyglot,logger, primary, address, name):
        self.logger = logger
        self.logger.info('Initializing Plex Webhook Polyglot...')

        self.httpService = None                         # Pointer for HTTP Service.
        self.poly = polyglot
        super(PlexController, self).__init__(polyglot, primary, address, name)
        self.name = 'Plex Webhook Listener'
        # Set in seconds (0 is default), if rapid_trigger = 0 code skipped.
        self.rapid_trigger = 0      
        self.sPoll = 60
        self.port = 9090

        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.CONFIG, self.cfgHandler)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.parameterHandler)
        polyglot.subscribe(polyglot.POLL, self.poll)

        polyglot.ready()
        polyglot.addNode(self)

    def stopServer(self):
        self.httpService.shutdown()
        self.httpService.server_close()
        self.httpService = None
        self.setDriver('ST', 0)
        self.setDriver('GV0', 0)

    def startServer(self):

        # Retrieve Local IP and set default port to use for HTTP Listener. 
        self.myip = self.get_poly_ip()
        if self.myip == None: 
            self.logger.error('Failed to Start Plex Webhook Polyglot. No IP to bind too.')
            return          # If no IP to bind to exit start. 

        # Start the HTTP Service to Listen for POSTs from a Plex Media Server.
        # When a valid post is recieved the PlexListener will call post_handler() below.
        self.httpService = HTTPServer((self.myip, self.port), PlexListener)
        self.thread  = Thread(target=self.httpService.serve_forever)
        self.thread.name = 'PlexListener'
        self.thread.daemon = True
        self.thread.start()
        self.logger.info('Successfully Started Polyglot Listener.')
        self.logger.info('Set you Plex Media Server Webhook URL to: http://{}:{}'.format(self.myip,self.port))
        
        self.setDriver('ST', 1)
        self.setDriver('GV0', self.port)
        self.setDriver('GV2', self.rapid_trigger)
        self.reportDrivers()

    def cfgHandler(self, config):
        if 'shortPoll' in config:
            self.sPoll = int(config['shortPoll'])

    def parameterHandler(self, params):
        # Check for Custom Parameters (port, rapid_trigger)
        if 'port' in params:
            self.port = int(params['port'])
            if self.port < 1024 or self.port > 49151: 
                self.logger.error('Custom Parameter: "port" must be between 1024-49151')
                self.port = 9090
        
        if 'rapid_trigger' in params:
            rt = int(params['rapid_trigger'])
            # rapid_trigger must be between 2 secs and poly.shortPoll.
            if 2 <= rt <= self.sPoll: 
                self.rapid_trigger = rt
                self.logger.info('Plex-Poly "rapid_trigger" feature turn ON set for: {} secs'.format(rt))
            else: 
                self.logger.error('Custom Parameter: "rapid_trigger" must be between 2-shortPoll({}) seconds.'.format(self.sPoll))


        if self.httpService is not None:
            # stop http service
            self.stopServer()

        self.startServer()

    def start(self):
        # Show values on startup if desired.
        self.logger.info('Starting Plex Webhook Polyglot...')
        self.poly.updateProfile()

        # Get a handler and set parent to myself, so we can process the POST requests.
        handle = PlexListener
        handle.parent = self

        # Show Webhook URL target and Explain the rapid_trigger feature.
        cfgdata = self.poly.getMarkDownData('POLYGLOT_CONFIG.md')
        cfgdata += 'Set your Plex Media Server Webhook URL to: http://{}:{} &nbsp;<br /><br /> <table><tbody><tr><td><strong>Rapid Trigger Feature Explained</strong></td></tr><tr> <td>This feature can alert your ISY if a user repeatedly presses play/pause/resume on their plex client.&nbsp;<br /> If they repeatedly cause an event within the rapid_trigger (seconds) value, the poly will internally flag them (Yellow Card).<br /> Then if they do this a second time, still within the trigger time, then the Rapid Trigger value will go <em>True</em> (Red Card).&nbsp;<br /> The Rapid Trigger Value will reset to <em>False</em> every shortPoll.</td>' .format(self.myip,self.port) 
        self.poly.setCustomParamsDoc(cfgdata)


    def get_poly_ip(self):
        try:
            s = socket(AF_INET, SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        except:
            ip = None
        finally:
            s.close()
        return ip
    
    def post_handler(self,time,payload):
        # Called from the PlexListener(BaseHTTPRequestHandler) when PLEX/POST recieved.
        # Passed in the Date/Time String and the Payload(Dictionary).
        
        # Identify the Plex Client from Payload(Dictionary)
        try: 
            # LTrim uuid max 14 characters for polyglot.node.address
            #self.logger.debug('Full uuid: {}'.format(payload["Player"]["uuid"]))
            uuid = payload["Player"]["uuid"].replace("-","")[:14].lower()
            devName = payload["Player"]["title"]
        except: #If "Player" or "event" do not exist then ignore post. 
            return

        # Check if new client.
        if self.poly.getNode(uuid) is None:
            self.poly.addNode(PlexClient(self.poly, self.address, uuid, devName, self.logger, self.rapid_trigger),update=True)
            self.setDriver("GV1", len(self.poly.getNodes())-1)

        # Update Node with new information about current action. 
        self.poly.getNode(uuid).update(time,payload)

    def poll(self, polltype):
        if 'shortPoll' in polltype:
            # If rapid_trigger is ON (not 0) turn off node.rapidFlag every shortPoll
            if self.rapid_trigger != 0:
                for node in self.poly.nodes():
                    if node.address != self.address:  # Ignore Controller Node
                        node.resetFlag()
        else: # longPoll
            self.setDriver("GV1", len(self.poly.getNodes())-1)
            self.reportDrivers()
            if not self.thread.is_alive(): 
                self.logger.error('longPoll - Restarting Polyglot and Listener.')
                self.startServer()

    def stop(self):
        self.stopServer()
        self.logger.info('Plex Webhook NodeServer stopped.')

    id = 'plexcontroller'

    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 2},
        {'driver': 'GV0', 'value': 0, 'uom': 56}, 
        {'driver': 'GV1', 'value': 0, 'uom': 56},
        {'driver': 'GV2', 'value': 0, 'uom': 58}
        ]
