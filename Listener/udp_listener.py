import socket
import struct
import logging
import sys
import time

# --- UDP Configuration ---
LISTEN_IP = '192.168.37.50' # L'IP della macchina dove lo script ascolta
LISTEN_PORT = 13750        # La porta su cui lo script ascolta

# --- Logging Configuration ---
# Set level to DEBUG to see everything.
# Stream to stderr so main process can capture it.
logging.basicConfig(level=logging.DEBUG, format='[UDP_STANDALONE] %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

def main():
    sock = None
    logger.info(f"Starting UDP receiver for {LISTEN_IP}:{LISTEN_PORT}")
    
    try:
        # 1. Create the socket
        logger.debug("Attempting to create UDP socket...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.debug("UDP socket created successfully.")

        # 2. Set socket options (RCVBUF, REUSEADDR - crucial for quick restarts)
        # SO_REUSEADDR allows binding to a port that's in TIME_WAIT state
        logger.debug("Setting SO_REUSEADDR option...")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1) # Allows multiple sockets to bind to the same address and port
        logger.debug("SO_REUSEADDR set.")

        # SO_RCVBUF increases the receive buffer size (good practice)
        logger.debug("Setting SO_RCVBUF to 1MB...")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2**20) # 1 MB
        logger.debug("SO_RCVBUF set.")
        
        # 3. Bind the socket
        logger.debug(f"Attempting to bind socket to {LISTEN_IP}:{LISTEN_PORT}...")

        try:
            sock.bind((LISTEN_IP, LISTEN_PORT))
            sock.setblocking(False) # Set to non-blocking to allow timeout handling and graceful shutdown

            logger.info(f"Successfully bound UDP receiver to {LISTEN_IP}:{LISTEN_PORT}. Waiting for packets...")
        except socket.error as e: 
            logger.critical(f"BIND ERROR: Failed to bind socket to {LISTEN_IP}:{LISTEN_PORT}: {e}")
            sys.exit(1) 

        # 4. Set a timeout for recvfrom (non-blocking in essence for event loop)
        logger.debug("Setting socket timeout to 0.1 seconds...")
        sock.settimeout(0.1) # Helps in a clean exit if no packets are received
        logger.debug("Socket timeout set.")

        packet_count = 0
        last_log_time = time.time()

        while True: # Loop until terminated by parent process
            try:
                # 5. Attempt to receive data
                data, addr = sock.recvfrom(1024) # Max packet size
                
                packet_count += 1
                current_time = time.time()
                if current_time - last_log_time > 1: # Log every second
                    logger.info(f"Received {packet_count} packets in the last second.")
                    packet_count = 0
                    last_log_time = current_time

                if len(data) == struct.calcsize('<f'): # Verify expected size (float)
                    received_distance = struct.unpack('<f', data)[0]
                    # Send distance to parent process via stdout
                    sys.stdout.write(f"DISTANCE:{received_distance:.2f}\n")
                    sys.stdout.flush() # Flush immediately to ensure parent gets data
                    logger.debug(f"Received and forwarded distance: {received_distance:.2f} m from {addr}")
                else:
                    logger.warning(f"Received malformed packet from {addr}, {len(data)} bytes. Expected {struct.calcsize('<f')} bytes.")
            
            except socket.timeout:
                # This is expected behavior if no packets arrive within the timeout
                pass 
            except Exception as e:
                logger.error(f"Unexpected error during UDP reception: {e}", exc_info=True) 
                time.sleep(0.1) # Small pause to prevent rapid error looping
                
    except socket.error as e:
        logger.critical(f"CRITICAL ERROR: Failed to create, bind, or configure UDP socket on {LISTEN_IP}:{LISTEN_PORT}: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Irrecoverable error in UDP receiver: {e}", exc_info=True)
    finally:
        if sock:
            sock.close()
            logger.info("UDP socket closed.")
        logger.info("UDP receiver process terminated.")

if __name__ == "__main__":
    main()