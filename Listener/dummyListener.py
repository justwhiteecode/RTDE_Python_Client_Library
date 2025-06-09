import socket
import struct
import logging
import threading
import sys
import select

# --- Parametri di configurazione del Ricevitore ---
LISTEN_IP = '192.168.37.50'  # Deve corrispondere a TARGET_NODE_IP del mittente
LISTEN_PORT = 13750          # Deve corrispondere a TARGET_NODE_PORT del mittente

# --- Setup del Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_udp_receiver(stop_event: threading.Event):
    """
    Avvia un server UDP per ascoltare i dati di distanza in arrivo.
    """
    sock = None
    try:
        # Crea un socket UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Lega il socket all'indirizzo IP e alla porta
        sock.bind((LISTEN_IP, LISTEN_PORT))
        logger.info(f"Ricevitore UDP in ascolto su {LISTEN_IP}:{LISTEN_PORT}")

        sock.settimeout(1.0) # Imposta un timeout per recvfrom per controllare l'evento di stop
        
        while not stop_event.is_set():
            try:
                # Ricevi dati
                data, addr = sock.recvfrom(1024)  # Dimensione del buffer 1024 byte
                
                # Decomprimi il valore float (assumendo un singolo float, '<f' per float little-endian)
                if len(data) == struct.calcsize('<f'):
                    distance = struct.unpack('<f', data)[0]
                    logger.info(f"Distanza ricevuta: {distance:.2f} m da {addr}")

                    
                else:
                    logger.warning(f"Ricevuto pacchetto malformato da {addr}. Dimensione: {len(data)} byte. Attesi {struct.calcsize('<f')} byte.")
                    
            except socket.timeout:
                # Timeout, continua il ciclo per controllare l'evento di stop
                continue
            except Exception as e:
                logger.error(f"Errore durante la ricezione dei dati UDP: {e}")
                break
            
    except socket.error as e:
        logger.error(f"Impossibile creare o legare il socket UDP: {e}")
    finally:
        if sock:
            sock.close()
            logger.info("Socket UDP chiuso.")
        logger.info("Thread del ricevitore UDP terminato.")

def main():
    stop_event = threading.Event()
    
    receiver_thread = threading.Thread(target=run_udp_receiver, args=(stop_event,))
    receiver_thread.daemon = True # Il thread si chiude con il programma principale
    receiver_thread.start()

    logger.info("Premi 'q' e Invio per uscire dal ricevitore.")
    
    try:
        # Mantieni il thread principale attivo e ascolta 'q' dalla console
        while not stop_event.is_set():
            # Usa select per controllare l'input senza bloccare
            if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]: # Timeout 0.1s
                line = sys.stdin.readline().strip()
                if line == 'q':
                    logger.info("Digitato 'q'. Segnalazione di spegnimento.")
                    stop_event.set()
                    break
            
    except KeyboardInterrupt:
        logger.info("Rilevata interruzione da tastiera (Ctrl+C). Chiusura in corso...")
        stop_event.set() # Segnala al thread di fermarsi
    finally:
        logger.info("In attesa che il thread del ricevitore termini...")
        receiver_thread.join(timeout=5) # Attendi che il thread termini graziosamente
        if receiver_thread.is_alive():
            logger.warning("Il thread del ricevitore non è terminato graziosamente.")
        logger.info("Applicazione ricevitore terminata.")

if __name__ == "__main__":
    main()