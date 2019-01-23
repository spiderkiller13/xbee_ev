#!/usr/bin/env python
from global_logger import logger 
import time
import random # for getMid()
import threading
import logging 
import socket, errno

#----- Parameters -----# 
WAIT_AWK_MAX_TIME = 3 # sec 
MAX_RESEND_TIMES = 6 # times 
START_CHAR = '['
END_CHAR = ']'
KEEPALIVE = 2 # sec ping,pong every 2 sec , 
KEPPALIVE_MAX = 4 # How long would you wait for PING,PONG, before abandon socket

# ------ Global Variable ---------# 
recbufList  = [] # [mid  ,  msg_type , content ]
recAwkDir = dict() # key: "MID" , value "AWK"

class SEND_AGENT(object):
    def __init__(self, bl_obj, payload, mid, qos = 1):
        self.payload  = payload 
        self.bl_obj = bl_obj
        self.mid = mid 
        self.is_awk = False
        self.qos = qos 
        #
        if qos == 1 : 
            self.send_thread = threading.Thread(target = self.send_target) 
            self.send_thread.start()
        elif qos == 0 : 
            self.send_thread = threading.Thread(target = self.send_no_trace) 
            self.send_thread.start()
        
    def send_no_trace(self) : 
        '''
        QOS = 0 
        for 'PING', 'PONG' , 'AWK'
        '''
        for i in range(MAX_RESEND_TIMES):
            if not self.bl_obj.is_connect:
                self.bl_obj.logger.info("[XBEE] Lost connection, Give up sending " + self.payload)
                return 
            try: 
                self.bl_obj.logger.info("[XBEE] Sending " + self.payload + "(" + self.mid + ")")
                self.bl_obj.sock.sendall( '['+self.payload+',mid'+ self.mid+']')
            except Exception as e : 
                self.bl_obj.logger.error("[XBEE] XBEE Error: " + str(e) )
                self.bl_obj.logger.error("[XBEE] Urge disconnected by send exception, when sending " + self.payload)
                self.bl_obj.is_connect = False 
                return 
            else: 
                self.is_awk = True 
                return 
        self.bl_obj.logger.error ("[XBEE] Fail to Send After trying " + str(MAX_RESEND_TIMES) + " times. Abort." )

    def send_target(self):
        '''
        QOS = 1,
        For CMD. 
        send with AWK callback , if can't received AWK, then resend it .
        '''
        global recAwkDir
        for i in range(MAX_RESEND_TIMES):
            if not self.bl_obj.is_connect:
                self.bl_obj.logger.info("[XBEE] Lost connection, Give up sending " + self.payload)
                return 
            #------ Send message -------#  # TODO 
            try: 
                self.bl_obj.logger.info("[XBEE] Sending: " + self.payload + "(" + self.mid + ")") # totally non-blocking even if disconnect
                self.bl_obj.sock.sendall( '['+self.payload+',mid'+ self.mid+']')
            except Exception as e :
                self.bl_obj.logger.error("[XBEE] BluetoothError: " + str(e) )
                self.bl_obj.logger.error("[XBEE] Urge disconnected by send exception, when sending " + self.payload)
                self.bl_obj.is_connect = False 
                return 
                # self.logger.error ("[XBEE] send_target() : "+ str(e) + ". Retry " + str(i) + "/" + str(MAX_RESEND_TIMES) ) 
                # time.sleep (1)
            else: 
                t_start = time.time() 
                while time.time() - t_start < WAIT_AWK_MAX_TIME: 
                    ans = recAwkDir.pop(self.mid, "not match") # Pop out element, if exitence 
                    if ans != "not match": # Get AWK 
                        self.bl_obj.logger.info("[XBEE] Get AWK (" + self.mid + ")")
                        self.is_awk = True 
                        break
                    else: # Keep waiting 
                        pass 
                    time.sleep (0.05)
            
                if self.is_awk : 
                    return 
                else: 
                    self.bl_obj.logger.warning("[XBEE] Need to resend "+ self.payload +" (" + str(i) + "/" + str(MAX_RESEND_TIMES) + ", "+ self.mid +")")
                    time.sleep(1) # for rest 
        self.bl_obj.logger.error ("[XBEE] Fail to Send After trying " + str(MAX_RESEND_TIMES) + " times. Abort." )

class BLUE_COM(object): 
    def __init__(self, logger, BT_cmd_CB, host=None , port = 3 ):
        # -------- Connection --------# 
        self.is_connect = False
        self.sock = None # Communicate sock , not server socket 
        self.recv_thread = None 
        self.engine_thread = None 
        self.is_engine_running = False  
        self.server_sock = None  # Only for Server 
        self.keepAlive_count = None 
        self.ping_count = None 
        self.host = host
        self.port = port 
        #-------- For Recevied -------# 
        self.logger = logger 
        self.BT_cmd_CB  = BT_cmd_CB
    
    ##########################
    ###   For Server Only  ###
    ##########################
    def server_engine_start(self): # Totolly blocking function 
        self.server_sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)# BluetoothSocket(RFCOMM)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(1) # Only accept 1 connection at 1 time

        self.is_engine_running = True 
        self.engine_thread = threading.Thread(target = self.server_engine)
        self.engine_thread.start()

    def server_engine_stop(self):
        self.shutdown_threads()
        try: 
            self.server_sock.close()
            self.logger.info("[XBEE] Server socket close.")
            self.server_sock = None
        except: 
            self.logger.error ("[XBEE] Can't close server socket.")
        # self.logger.info("[XBEE] server engine stop ")
    
    def server_engine (self): # ToTally Blocking 
        global recbufList
        self.server_sock.settimeout(5)
        #try:
        if True : 
            while self.is_engine_running: # Durable Server
                if self.is_connect : 
                    # ------- Check Keep alive for client  -------# 
                    if time.time() - self.keepAlive_count >= KEPPALIVE_MAX : # Give up connection
                        self.close(self.sock)
                        self.logger.warning ("[XBEE] Disconnected, because client did't send PING. (PING, PONG)")
                    if recbufList != []:
                        msg = recbufList.pop(0) # FIFO, check what I received 
                        if   msg[1] == 'DISCONNECT': # Close connection with  client 
                            self.close(self.sock)
                        elif msg[1] == 'PING':
                            self.logger.info("[XBEE] Get PING  ")
                        elif msg[1] == 'CMD':
                            self.logger.info("[XBEE] Get cmd ")
                        else: 
                            self.logger.error("[XBEE] Unresconized cmd: " + msg[1]) 
                    else:
                        self.logger.debug ("nothing to do ")
                    
                else: # Need to Reconnect 
                    self.logger.debug("[XBEE] Waiting for connection on port %d" % self.port)
                    try: 
                        client_sock, client_info = self.server_sock.accept()
                    except socket.error, e:
                        if e.args[0] == errno.EWOULDBLOCK or e.args[0] == errno.ETIMEDOUT:
                            self.logger.debug('[XBEE] Still waiting for client.')
                        else: 
                            self.logger.error('[XBEE] Error at Server Engine: ' + str(e))
                    else: 
                        self.sock = client_sock
                        self.logger.info("[XBEE] Accepted connection from "+  str(client_info))
                        self.is_connect = True 
                        self.keepAlive_count = time.time() 
                        
                        self.recv_thread = threading.Thread(target = self.recv_engine) # , args=(self.sock,))
                        self.recv_thread.start()
                time.sleep(0.1) 
        #except: 
        else: 
            self.logger.error("[XBEE] Something wrong at server_engine.")
        
        self.logger.info("[XBEE] END of server_engine")
    

    ###########################
    ###   For Client Only   ###
    ###########################
    def client_engine_start(self):
        self.is_engine_running = True
        self.engine_thread = threading.Thread(target = self.client_engine)
        self.engine_thread.start()
    
    def client_engine_stop(self):
        self.client_disconnect_qos0() # Block for 3 sec to send DISCONNECT to server . 
        self.shutdown_threads()
        self.logger.info("[XBEE] client engine stop ")

    def client_engine(self):
        while self.is_engine_running: 
            if self.is_connect: 
                # ------- PING PONG -------# Keep alive 
                if time.time() - self.keepAlive_count >= KEPPALIVE_MAX : # Give up connection
                    self.close(self.sock)
                    self.logger.warning ("[XBEE] Disconnected, because KEEPAVLIE isn't response. (PING, PONG)")
                elif  time.time() - self.ping_count >= KEEPALIVE: # Only for client to send "PING"
                    self.send('PING', 0)
                    self.ping_count = time.time()
                #------- Check List --------# 
                if recbufList != []: # Something to do 
                    msg = recbufList.pop(0)
                    self.BT_cmd_CB(msg)
            else: 
                # logger.info("[client_engine] Reconnected.")
                if not self.client_connect(self.host, self.port):
                    time.sleep(1) # Sleep 1 sec for next reconnection
            time.sleep(0.1)

    def client_connect  (self, host, port = 3):
        '''
        Only for client socket 
        '''
        self.logger.info("[XBEE] connecting to " + host)
        ts = time.time()
        # Create the client socket
        self.sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.sock.setblocking(False) # Non-blocking 
        # self.sock.settimeout(10) # Timeout 10 sec  # TODO This will cause the bug 
    
        rc = self.sock.connect_ex((self.host, self.port))
        if rc == 0 :  # Conncetion success
            output  = True 
            self.is_connect = True 
            self.keepAlive_count = time.time()
            self.ping_count = time.time()
            self.sock.setblocking(False) # Non-blocking 
            self.logger.info("[XBEE] connected. Spend " + str(time.time() - ts) + " sec.") #Link directly, Faster ????? TODO 

            self.recv_thread = threading.Thread(target = self.recv_engine)# , args=(self.sock,))  # (self.sock))
            self.recv_thread.start()
        else: # Exception 
            self.logger.error("[XBEE] Not able to Connect, " + errno.errorcode[rc] )
            output = False 
        return output 

    def client_disconnect_qos1(self): # Normally disconnect  # Only from client -> server 
        if self.is_connect: 
            rc = self.send("DISCONNECT", 1)
            t_s = time.time() 
            while not rc.is_awk:
                if time.time() - t_s  > 3 : # Only wait 3 sec
                    self.logger.warning ("[XBEE] Fail to send DISCONNECT in 3 sec.") 
                    break
        else: 
            self.logger.warning ("[XBEE] No need for disconnect, Connection already lost.")
    
    def client_disconnect_qos0(self): # Normally disconnect  # Only from client -> server 
        if self.is_connect: 
            self.send("DISCONNECT", 0)
        else: 
            self.logger.warning ("[XBEE] No need for disconnect, Connection already lost.")
    #########################
    ###   General Usage   ###
    #########################
    def shutdown_threads(self):
        '''
        Include close socket 
        '''
        self.is_connect = False
        self.is_engine_running = False
        # -------------------------------# 
        '''
        try:
            if self.recv_thread == None :
                self.logger.info("[XBEE] recv_thread didn't start yet ....")
            else:
                self.logger.info("[XBEE] Waiting recv thread to join...")
                self.recv_thread.join(10)
        except : 
            self.logger.error("[XBEE] Fail to join recv thread.")
        '''
        self.close(self.sock)
        try:
            if self.engine_thread == None : 
                self.logger.info("[XBEE] engine_thread didn't start yet ....")
            else: 
                self.logger.info("[XBEE] Waiting engine_thread to join...")
                self.engine_thread.join(10)
        except : 
            self.logger.error("[XBEE] Fail to join engine_thread.")
        
    
    def close(self, socket): 
        self.is_connect = False  # P2P
        # -------------------------------_# 
        try: # to close recv_threading 
            if self.recv_thread == None : 
                self.logger.info("[XBEE] recv_thread didn't start yet ....")
            else: 
                if self.recv_thread.is_alive():
                    self.logger.info ("[XBEE] waiting join recv_threading ")
                    self.recv_thread.join(5)
                self.logger.info ("[XBEE] close recv_threading")
        except : 
            self.logger.error ("[XBEE] Exception at close recv_thread.")
        try: 
            socket.close()
            self.logger.info("[XBEE] Socket close.")
            socket = None
        except: 
            self.logger.error ("[XBEE] Can't close socket .")
    
    def getMid(self):
        '''
        return 'AUTK', 'UROR', 'QMGT' in random
        '''
        output = "" 
        for i in range(4) : 
            output += chr(random.randint(0,25) + 65)
        return output

    def send (self, payload, qos = 1, mid = None):
        '''
        Inptu : payload need to be String 
        nonblocking send.
        return SEND_AGENT
        '''
        if mid == None : 
            mid = self.getMid()
        return SEND_AGENT(self, payload, mid, qos)

    def recv_engine(self):
        '''
        Both Server and Client need recv_engine for receiving any message.
        '''
        global recbufList, recAwkDir
        self.sock.settimeout(1)
        while self.is_connect:
            #---------RECV -----------# 
            try: 
                rec = self.sock.recv(1024) # Blocking for 1 sec. 
            except Exception as e:
                if e.args[0] == 'timed out':
                    self.logger.debug("[XBEE] recv Timeout." )
                else:
                    self.logger.error("[XBEE] Error: " + str(e) )
                    self.logger.error("[XBEE] Urge disconnected by recv exception.")
                    self.is_connect = False 
            else:
                if rec == "":
                    time.sleep(0.1)
                    continue
                
                self.logger.debug("rec: " + rec)
                is_valid = False 
                try:
                    #---------  Check start and end Char -------# 
                    if rec[0] == START_CHAR or rec[-1] == END_CHAR:
                        rec = rec[1:-1] # Del '[' and ']'
                        mid_str = rec[-8:]# ,midASDF
                        rec = rec[:-8] # Cut off mid 
                        #---------  Check MID --------# 
                        if mid_str[:4] != ',mid' or (not mid_str[4:].isupper()):
                            pass 
                        else: 
                            is_valid = True 
                    else: 
                        pass 
                except: 
                    is_valid = False 
                    self.logger.error ("[XBEE] recv_engine MID ERROR ")

                if is_valid: 
                    self.logger.info ("[XBEE] Received: " + rec )
                    if rec == "AWK":
                        recAwkDir[mid_str[4:]] = rec
                    elif rec == "PING": # Server recv 
                        self.keepAlive_count = time.time()
                        self.send('PONG', 0, mid=mid_str[4:]) # Send the same mid with PING 
                    elif rec == "PONG":# Client  recv 
                        self.keepAlive_count = time.time()
                    else:
                        # self.logger.debug("[XBEE] Sending AWK")
                        self.send('AWK', 0, mid = mid_str[4:])
                        
                        if rec == "DISCONNECT":
                            recbufList.append([mid_str[4:], rec , ""])
                        else :  # CMD
                            recbufList.append([mid_str[4:], "CMD" , rec ])
                            self.BT_cmd_CB(rec)
                else: 
                    self.logger.error("[XBEE] received not valid msg.")
                # ------ Reset Flag --------# 
                rec = ""
                # End of else 
            time.sleep(0.1)
            # End of while 
