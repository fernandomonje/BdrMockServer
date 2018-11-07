#!/opt/ActivePython-3.6/bin/python3
# -*- coding: utf-8 -*-
__author__ = "Fernando Monje"
__copyright__ = "Copyright 2018, Cleartech LTDA"
__credits__ = ["Fernando Monje", "Gabriel Monje"]
__version__ = "1.0.0"
__maintainer__ = "Fernando Monje"
__email__ = "fcardoso@cleartech.com.br"
__status__ = "Production"

from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from xml.etree import ElementTree
import ssl
import datetime
import random
import http.client, urllib.parse
import sys
import argparse
import os

""" 
  Constants Definition
	This values should be adjusted based on the BDR Server 
	and Environment to be used.
	The server.pem and cacert.pem files should match the current 
	server certificate and CA certificate.
	The server.pem file should contains the certificate and the 
	matching private key for the certificate.
"""
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
LISTEN_ADDR = '10.100.102.51'
SERVER_CERT = BASE_DIR + '/ssl/server.pem'
CLIENT_CERTS = BASE_DIR + '/ssl/cacert.pem'
UTC_DATE_TIME = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
  """
     HTTP(S) Server Request Handler
     This class implementation defines only the POST http method
     since the BDR server only accept this kind of method.
     Here we handle the SOAP envelope in a particular way, we 
     do not implement any type of library for SOAP handling since this
     server is intended for tests propouses only.
  """
  def log_message(self, format, *args):
    return
  def do_POST(self):
    """
       Since SPG POST the data using chuncked feature, we need to
       read the data in chunks.
    """
    if not self.headers['Content-Length']:
      if self.headers['Transfer-Encoding'] == 'chunked':
        data_body = ""
        while True:
          chunk_size = self.get_chunk_size(self.rfile)
          if (chunk_size == 0):
            break
          else:
            chunk_data = self.get_chunk_data(chunk_size, self.rfile)
            data_body += chunk_data.decode()
        body = data_body
    else:
      content_length = int(self.headers['Content-Length'])
      body = self.rfile.read(content_length)
    """
      After reading the SOAP message in the HTTP POST we
      start the xml data extraction process.
    """
    soap_header = self.getSoapHeader(body)
    soap_body = self.getSoapMsg(body) 
    msgType = self.getMsgType(soap_body.text)
    spid = self.getSpid(soap_body.text)
    session_id = self.genSessionId()
    header = self.genHeader(spid,session_id)
    """
      After gather all the data needed, we send the HTTP status
      (always returns 200, since this server is intended for tests
       propouses only). Then we write the SOAP syn ack thru the
       socket. The SOAP syn ack will always have the value 0(zero)
       to keep the behaviour consistent with the HTTP status.
    """
    self.send_response(200)
    response = BytesIO()
    soap_ack_string = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:SOAP-ENC=\"http://schemas.xmlsoap.org/soap/encoding/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:bdr=\"BDR/SoapServer\"><SOAP-ENV:Body><bdr:sendMessageResponse><bdr:result>0</bdr:result></bdr:sendMessageResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>\n"
    self.send_header("Content-Type","text/xml; charset=utf-8")
    response.write(soap_ack_string.encode())
    self.send_header("Content-Length", response.getbuffer().nbytes)
    self.end_headers()
    self.wfile.write(response.getvalue())
    """
       Here we send the asynchronous XML message encapsulated in
       the SOAP envelope.
       The XML message to be send is based in the message that was received
       from SPG.
    """
    sendXmlReply(msgType, header, spid, session_id)

  """
    Definition of some helpers methods
  """
  def get_chunk_size(self, stringio):
    size_str = stringio.read(2)
    while size_str[-2:] != b"\r\n":
        size_str += stringio.read(1)
    return int(size_str[:-2], 16)

  def get_chunk_data(self, chunk_size, stringio):
    data = stringio.read(chunk_size)
    stringio.read(2)
    return data

  def getSoapHeader(self, body):
    namespaces = {
      'soap': 'http://www.w3.org/2003/05/soap-envelope',
      'soap1': 'BDR/SoapServer'
    }
    dom = ElementTree.fromstring(body)
    header_el = dom.findall('./soap:Body'
                        '/soap1:sendMessage'
                        '/soap1:item0',
                        namespaces,)
    if not header_el:
       header_el = dom.findall('./soap:Body'
                        '/soap1:sendMessage'
                        '/soap1:header',
                        namespaces,)
    if not header_el:
      namespaces = {
      'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
      }
      header_el = dom.findall('./soapenv:Body'
                        '/{BDR/SoapServer}sendMessage'
                        '/{BDR/SoapServer}header',
                        namespaces,)
    return header_el[0]

  def getSoapMsg(self, body):
    namespaces = {
      'soap': 'http://www.w3.org/2003/05/soap-envelope',
      'soap1': 'BDR/SoapServer'
    }
    dom = ElementTree.fromstring(body)
    body_el = dom.findall('./soap:Body'
                        '/soap1:sendMessage'
                        '/soap1:arg0',
                        namespaces,)
    if not body_el:
      body_el = dom.findall('./soap:Body'
                        '/soap1:sendMessage'
                        '/soap1:msg',
                        namespaces,)
    if not body_el:
      namespaces = {
      'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
      }
      body_el = dom.findall('./soapenv:Body'
                        '/{BDR/SoapServer}sendMessage'
                        '/{BDR/SoapServer}msg',
                        namespaces,)
    return body_el[0]

  def getMsgType(self, xml):
    """
      This method read and xml object and try to get the MsgType based 
      on the XML tags.
      The return is the type of service and the asynchronous message type
      of the xml message that was received.
    """
    date_log = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    tree = ElementTree.ElementTree(ElementTree.fromstring(xml))
    if tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/{urn:brazil:lnp:1.0}NewSession'):
      print(date_log + '|SPG => BDR|BDO|NewSession|200|')
      return 'BDO_NewSessionReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/{urn:brazil:lnp:1.0}DownloadRecoveryRequest'):
      print(date_log + '|SPG => BDR|BDO|DownloadRecoveryRequest|200|')
      return 'BDO_DownloadRecoveryReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/{urn:brazil:lnp:1.0}SwimRecoveryComplete'):
      print(date_log + '|SPG => BDR|BDO|SwimRecoveryComplete|200|')
      return 'BDO_SwimRecoveryCompleteReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/{urn:brazil:lnp:1.0}RecoveryCompleteRequest/'):
      print(date_log + '|SPG => BDR|BDO|RecoveryCompleteRequest|200|')
      return 'BDO_RecoveryCompleteReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/{urn:brazil:lnp:1.0}NewSession'):
      print(date_log + '|SPG => BDR|SOA|NewSession|200|')
      return 'SOA_NewSessionReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/{urn:brazil:lnp:1.0}NotificationRecoveryRequest'):
      print(date_log + '|SPG => BDR|SOA|NotificationRecoveryRequest|200|')
      return 'SOA_NotificationRecoveryReply'
    elif tree.find('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/{urn:brazil:lnp:1.0}SwimRecoveryComplete'):
      print(date_log + '|SPG => BDR|SOA|SwimRecoveryComplete|200|')
      return 'SOA_SwimRecoveryCompleteReply'
    elif tree.findall('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/{urn:brazil:lnp:1.0}*'):
      print(date_log + '|SPG => BDR|SOA|RecoveryCompleteRequest|200|')
      return 'SOA_RecoveryCompleteReply'
    else:
      if tree.findall('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/*'):
        for el in tree.findall('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}BDOtoBDR/*'):
          if el.tag == '{urn:brazil:lnp:1.0}RecoveryCompleteRequest':
            print(date_log + '|SPG => BDR|BDO|RecoveryCompleteRequest|200|')
            return 'BDO_RecoveryCompleteReply'
          elif  el.tag == '{urn:brazil:lnp:1.0}ClientReleaseSession':
            print(date_log + '|SPG => BDR|BDO|ClientReleaseSession|200|')
            return 'ClientReleaseSession'
          elif el.tag == '{urn:brazil:lnp:1.0}ClientKeepAlive':
            print(date_log + '|SPG => BDR|BDO|ClientKeepAlive|200|')
            return 'ClientKeepAlive'
      elif tree.findall('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/*'):
        for el in tree.findall('./{urn:brazil:lnp:1.0}messageContent/{urn:brazil:lnp:1.0}SOAtoBDR/*'):
          if el.tag == '{urn:brazil:lnp:1.0}RecoveryCompleteRequest':
            print(date_log + '|SPG => BDR|SOA|RecoveryCompleteRequest|200|')
            return 'SOA_RecoveryCompleteReply'
          elif el.tag == '{urn:brazil:lnp:1.0}ClientReleaseSession':
            print(date_log + '|SPG => BDR|SOA|ClientReleaseSession|200|')
            return 'ClientReleaseSession'
          elif el.tag == '{urn:brazil:lnp:1.0}ClientKeepAlive':
            print(date_log + '|SPG => BDR|SOA|ClientKeepAlive|200|')
            return 'ClientKeepAlive'
      print(date_log + '|SPG => BDR|UNDEFINED_SERVICE|UNDEFINED_MESSAGE|200|')
      print(xml)
      return None

  def getSpid(self,xml):
    tree = ElementTree.ElementTree(ElementTree.fromstring(xml))
    spid = tree.find('./{urn:brazil:lnp:1.0}messageHeader/{urn:brazil:lnp:1.0}service_prov_id').text
    return spid

  def genSessionId(self):
    return random.randint(900000000, 900000050)
  def genHeader(self, spid, session_id):
    return spid + '|0|' + str(session_id) + '|1|3|'
  


def sendXmlReply(msgType, header, spid, session_id):
  """
    This method open an HTTPS connection with the client SPG to
    send the XML message encapsulated in the SOAP envelop.
  """
  global clientPort
  global clientHost
  global clientOs
  date_log = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
  if msgType == 'ClientReleaseSession':
    return
  elif msgType == 'ClientKeepAlive':
    return
  service_type = msgType.split('_')[0]
  context = ssl.SSLContext(ssl.PROTOCOL_TLS)
  context.verify_mode = ssl.CERT_REQUIRED
  context.load_verify_locations(CLIENT_CERTS)
  conn = http.client.HTTPSConnection(clientHost, port=int(clientPort), context=context, cert_file=SERVER_CERT)
  with open(BASE_DIR + '/templates/' + msgType + '.xml', 'r') as xmlFile:
    xmlData = xmlFile.read().replace('\n', '').replace('SPID', spid).replace('DDDDDD', UTC_DATE_TIME).replace('SSSSSS', str(session_id)).replace('<', '&lt;')
  soap_env = '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:soap="BDR/SoapServer"><soapenv:Header/><soapenv:Body>\
              <soap:sendMessage><soap:header>' + header + '</soap:header><soap:msg>' + xmlData + '</soap:msg></soap:sendMessage>\
              </soapenv:Body></soapenv:Envelope>'
  headers = { "Content-Type" : "text/xml; charset=utf-8" }
  if clientOs.upper() == 'WIN':
    if service_type == 'BDO':
      conn.request('POST', '/' + spid + '_BDRBDOSOAPReceiverService/BDRBDOSOAPReceiverService.asmx', soap_env, headers=headers)
    elif service_type == 'SOA':
      conn.request('POST', '/' + spid + '_BDRSOAPReceiverService/BDRSOAPReceiverService.asmx', soap_env, headers=headers)
  elif clientOs.upper() == 'LINUX':
    if service_type == 'BDO':
      conn.request('POST', '/axis2/services/' + spid + '_BDRBDOSOAPReceiverService', soap_env)
    elif service_type == 'SOA':
      conn.request('POST', '/axis2/services/' + spid + '_BDRSOAPReceiverService', soap_env)    
  response = conn.getresponse()
  print(date_log + '|BDR => SPG|' + msgType.split('_')[0] + '|' + msgType.split('_')[1] + '|' + str(response.status)+ '|')
  #print(response.status, response.reason)
  data = response.read()
  #print(data)
  conn.close()

if __name__ == '__main__':
    """The main program function.

       ...

       It will instantiate a server class and server forever using the hostname/ip and port supplied.
       The server_class variable will contains the server class to be used.
       If there is a keyboard interruption the server will stops..
    """
    # Argument Parser Definitions
    parser = argparse.ArgumentParser(description='Portability Test Server.') 
    parser.add_argument('--client-port', required=True, help='Client Port to be used to send messages (SPG Port)', type=int, metavar='SPG_PORT')
    parser.add_argument('--client-address', required=True, help='Client address to be used to send messages (SPG address)', metavar='SPG_ADDRESS')
    parser.add_argument('--client-os', required=True, choices=['win', 'WIN', 'linux', 'LINUX'], help='Client OS type (win, linux)', metavar='SPG_OS')
    parser.add_argument('--server-port', required=True, help='Server Port to be opened to the Client (BDR Port)', type=int, metavar='BDR_SERVER_PORT')
    args = parser.parse_args()
    clientPort = args.client_port
    clientHost = args.client_address
    clientOs = args.client_os
    serverPort = args.server_port

    date_log = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    # HTTPS Server Definitions & Initiation
    server_class = HTTPServer
    httpd = server_class((LISTEN_ADDR, int(serverPort)), SimpleHTTPRequestHandler)
    httpd.socket = ssl.wrap_socket (httpd.socket,
                                    keyfile=SERVER_CERT,
                                    certfile=SERVER_CERT, server_side=True, ssl_version=ssl.PROTOCOL_TLS)
    try:
      print(date_log + ' - Portability Test Server Starting')
      httpd.serve_forever()
    except KeyboardInterrupt:
      pass
    except Exception as e:
      print(date_log + ' - Failed to Start Portability Test Server')
      sys.exit(1)
    httpd.server_close()
    print(date_log + ' - Portability Test Server Stoped')
