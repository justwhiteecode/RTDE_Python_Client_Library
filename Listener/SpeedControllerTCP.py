import socket
import struct
import logging
import threading
import sys
import time
import select
from queue import Queue, Empty

# --- Importazioni per RTDE ---
sys.path.append("/home/ubuntu/RTDE_Python_Client_Library")
import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

# --- Configurazioni ---
LISTEN_IP = '192.168.37.50'
LISTEN_PORT = 13750

ROBOT_HOST = "10.4.1.87"
ROBOT_PORT = 30004
CONFIG_XML = './recipe.xml'
RTDE_FREQUENCY = 125 # Frequenza di aggiornamento RTDE in Hz.

# --- Fasce di velocità ---
VELOCITY_THRESHOLD_0_5M     = 0.0
VELOCITY_THRESHOLD_1M       = 0.25
VELOCITY_THRESHOLD_2M       = 0.5
VELOCITY_THRESHOLD_3M       = 0.7
VELOCITY_THRESHOLD_OVER_3M  = 1.0

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Queue per la distanza ---
distance_queue = Queue()

# Variabili globali per la gestione della connessione TCP
global_client_socket = None
global_client_addr = None
global_tcp_server_listening_event = threading.Event()
global_tcp_client_connected_event = threading.Event()

def calculate_speed_fraction(distance: float) -> float:
    if distance < 0:
        return VELOCITY_THRESHOLD_OVER_3M
    elif distance < 0.5:
        return VELOCITY_THRESHOLD_0_5M
    elif 0.5 <= distance < 1.0:
        return VELOCITY_THRESHOLD_1M
    elif 1.0 <= distance < 2.0:
        return VELOCITY_THRESHOLD_2M
    elif 2.0 <= distance < 3.0:
        return VELOCITY_THRESHOLD_3M
    else:
        return VELOCITY_THRESHOLD_OVER_3M

def run_tcp_server_receiver(stop_event: threading.Event):
    global global_client_socket
    global global_client_addr
    global global_tcp_server_listening_event
    global global_tcp_client_connected_event

    server_sock = None
    try:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536) 
        logger.debug("[TCP_SERVER_RX] Dimensione buffer di ricezione impostata a 64KB.")

        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((LISTEN_IP, LISTEN_PORT))
        server_sock.listen(1)
        server_sock.settimeout(1.0)
        logger.info(f"[TCP_SERVER_RX] In ascolto su {LISTEN_IP}:{LISTEN_PORT}")
        global_tcp_server_listening_event.set()

        while not stop_event.is_set():
            if global_client_socket is None:
                global_tcp_client_connected_event.clear()
                logger.info("[TCP_SERVER_RX] In attesa di una connessione client...") 
                try:
                    conn, addr = server_sock.accept()
                    global_client_socket = conn
                    global_client_addr = addr
                    global_client_socket.setblocking(True)
                    global_tcp_client_connected_event.set()
                    logger.info(f"[TCP_SERVER_RX] Connesso da {global_client_addr}")
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"[TCP_SERVER_RX] Errore durante l'accettazione della connessione: {e}")
                    time.sleep(1)
                    continue

            try:
                data = global_client_socket.recv(4) 
                
                if not data:
                    logger.warning(f"[TCP_SERVER_RX] Connessione chiusa da {global_client_addr}")
                    global_client_socket.close()
                    global_client_socket = None
                    global_client_addr = None
                    global_tcp_client_connected_event.clear()
                    continue

                if len(data) == struct.calcsize('<f'):
                    received_distance = struct.unpack('<f', data)[0]
                    
                    with distance_queue.mutex:
                        distance_queue.queue.clear()
                    distance_queue.put(received_distance)
                    logger.debug(f"[TCP_SERVER_RX] Ricevuto distanza: {received_distance:.2f} da {global_client_addr}")
                else:
                    logger.warning(f"[TCP_SERVER_RX] Pacchetto malformato da {global_client_addr}, {len(data)} byte. Attesi 4.")
                
            except socket.error as e:
                logger.error(f"[TCP_SERVER_RX] Errore di socket durante la ricezione da {global_client_addr}: {e}. Disconnesso.")
                if global_client_socket:
                    global_client_socket.close()
                global_client_socket = None
                global_client_addr = None
                global_tcp_client_connected_event.clear()
                time.sleep(1)
            except Exception as e:
                logger.error(f"[TCP_SERVER_RX] Errore generico durante la ricezione da {global_client_addr}: {e}. Disconnesso.")
                if global_client_socket:
                    global_client_socket.close()
                global_client_socket = None
                global_client_addr = None
                global_tcp_client_connected_event.clear()
                time.sleep(1)

    except Exception as e:
        logger.critical(f"[TCP_SERVER_RX] Errore critico avvio server TCP: {e}")
        stop_event.set()
    finally:
        if global_client_socket:
            global_client_socket.close()
        if server_sock:
            server_sock.close()
        logger.info("[TCP_SERVER_RX] Thread server TCP terminato.")

# --- Controller RTDE per Robot UR ---
def run_rtde_controller(stop_event: threading.Event):
    con = None
    input_data = None
    current_distance = -1.0
    # Memorizza l'ultima velocità impostata per evitare spam di log
    last_speed_fraction = -1.0 

    logger.info("[RTDE_TX] In attesa che il server TCP sia pronto...")
    global_tcp_server_listening_event.wait()
    logger.info("[RTDE_TX] Server TCP pronto.")

    while not stop_event.is_set(): # Ciclo esterno per gestire la riconnessione RTDE
        try:
            logger.info("[RTDE_TX] Tentativo di connessione al robot UR...")
            con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
            
            # Ciclo di connessione iniziale
            while not con.is_connected() and not stop_event.is_set():
                if con.connect() == 0: # 0 significa errore di connessione
                    logger.warning("[RTDE_TX] Connessione al robot fallita, riprovo in 1 secondo...")
                    time.sleep(1)
                else:
                    logger.info("[RTDE_TX] Connesso al robot.")

            if not con.is_connected():
                # Se il ciclo di connessione si è interrotto a causa di stop_event
                logger.info("[RTDE_TX] Interruzione richiesta durante la connessione al robot.")
                break # Esci dal ciclo esterno

            # Configurazione RTDE (eseguita solo dopo una connessione riuscita)
            conf = rtde_config.ConfigFile(CONFIG_XML)
            input_names, input_types = conf.get_recipe('in')
            output_names, output_types = conf.get_recipe('out')

            con.send_output_setup(output_names, output_types, RTDE_FREQUENCY)
            input_data = con.send_input_setup(input_names, input_types)

            if input_data:
                input_data.speed_slider_mask = 1
            else:
                logger.critical("[RTDE_TX] Errore configurazione input.")
                # Non è un errore da riconnettere, è un problema di configurazione
                stop_event.set() 
                break # Esci dal ciclo esterno

            if not con.send_start():
                logger.critical("[RTDE_TX] Fallita sincronizzazione RTDE. Riprovo la connessione.")
                # Questo porterà alla chiusura della connessione e un nuovo tentativo nel ciclo esterno
                con.disconnect() 
                continue # Riprova il ciclo esterno (nuova connessione)

            logger.info("[RTDE_TX] RTDE avviato e sincronizzato.")

            # Ciclo principale di controllo RTDE mentre la connessione è attiva
            while con.is_connected() and not stop_event.is_set():
                if not global_tcp_client_connected_event.is_set():
                    if last_speed_fraction != VELOCITY_THRESHOLD_OVER_3M:
                        logger.info("[RTDE_TX] Nessun client TCP connesso. Velocità impostata al 100%.")
                        last_speed_fraction = VELOCITY_THRESHOLD_OVER_3M
                        input_data.speed_slider_fraction = VELOCITY_THRESHOLD_OVER_3M
                        #con.send(input_data)
                    logger.debug(f"[RTDE_TX] Velocità corrente (nessun client): {input_data.speed_slider_fraction*100:.0f}%")
                    time.sleep(1 / RTDE_FREQUENCY)
                    continue

                #state = con.receive()
                if True: #state: # Se ricevo dati, la connessione è attiva
                    try:
                        while True:
                            current_distance = distance_queue.get_nowait()
                    except Empty:
                        pass # Nessun nuovo dato, usa l'ultimo

                    current_speed_fraction = calculate_speed_fraction(current_distance)

                    if input_data.speed_slider_fraction != current_speed_fraction:
                        input_data.speed_slider_fraction = current_speed_fraction
                        #con.send(input_data)
                        logger.info(f"[RTDE_TX] Distanza: {current_distance:.2f} m -> Velocità: {current_speed_fraction*100:.0f}% (Aggiornata)")
                        last_speed_fraction = current_speed_fraction

                    logger.debug(f"[RTDE_TX] Velocità corrente: {input_data.speed_slider_fraction*100:.0f}%")
                else:
                    # Se state è None, significa che la connessione RTDE è stata persa
                    logger.warning("[RTDE_TX] Connessione RTDE persa (received None from Controller). Tentativo di riconnessione...")
                    break # Esci dal ciclo interno, per riprovare la connessione nel ciclo esterno
                
                time.sleep(1 / RTDE_FREQUENCY)

        except rtde.RTDEException as e:
            # Cattura errori specifici RTDE, come "received 0 bytes from Controller"
            logger.error(f"[RTDE_TX] Errore RTDE: {e}. Tentativo di riconnessione...")
            if con and con.is_connected():
                con.disconnect() # Assicura la disconnessione pulita prima di riprovare
            time.sleep(1) # Breve pausa prima di riprovare
            continue # Riprova il ciclo esterno
        except Exception as e:
            logger.critical(f"[RTDE_TX] Errore generico nel thread RTDE: {e}. Tentativo di riconnessione...")
            if con and con.is_connected():
                con.disconnect()
            time.sleep(1) # Breve pausa prima di riprovare
            continue # Riprova il ciclo esterno
        finally:
            if con and con.is_connected():
                con.send_pause()
                con.disconnect()
            # Non loggo "Thread RTDE terminato" qui, perché il thread continua a girare
            # finché stop_event non è settato.

    logger.info("[RTDE_TX] Thread RTDE terminato.") # Solo quando l'intero thread si ferma

# --- Funzione Principale ---
def main():
    stop_event = threading.Event()

    tcp_server_thread = threading.Thread(target=run_tcp_server_receiver, args=(stop_event,), daemon=True)
    tcp_server_thread.start()

    rtde_thread = threading.Thread(target=run_rtde_controller, args=(stop_event,), daemon=True)
    rtde_thread.start()

    logger.info("Premi 'q' e Invio per uscire.")

    try:
        while not stop_event.is_set():
            if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                user_input = sys.stdin.readline().strip()
                if user_input == 'q':
                    logger.info("Interruzione richiesta. Chiusura in corso...")
                    stop_event.set()
                else:
                    logger.info(f"Comando '{user_input}' non riconosciuto. Premi 'q' e Invio per uscire.")
    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera. Chiusura in corso...")
        stop_event.set()
    finally:
        tcp_server_thread.join(timeout=5)
        rtde_thread.join(timeout=5)
        logger.info("Tutti i thread terminati.")

if __name__ == "__main__":
    main()