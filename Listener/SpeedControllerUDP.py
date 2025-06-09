import logging
import threading
import sys
import time
import select
from queue import Queue, Empty
import subprocess
import os

# --- Importazioni per RTDE ---
sys.path.append("/home/ubuntu/RTDE_Python_Client_Library")
try:
    import rtde.rtde as rtde
    import rtde.rtde_config as rtde_config
except ImportError:
    print("Errore: La libreria RTDE non è stata trovata. Assicurati che il percorso sia corretto e la libreria sia installata.")
    sys.exit(1)

# --- Configurazioni Globali ---
ROBOT_HOST = "10.4.1.87"
ROBOT_PORT = 30004
CONFIG_XML = './recipe.xml' # Assicurati che questo sia il percorso corretto per il tuo recipe.xml
RTDE_FREQUENCY = 100 # Hz

# --- Fasce di velocità ---
VELOCITY_THRESHOLD_0_5M      = 0.0
VELOCITY_THRESHOLD_1M        = 0.25
VELOCITY_2M_THRESHOLD        = 0.5
VELOCITY_3M_THRESHOLD        = 0.7
VELOCITY_OVER_3M_THRESHOLD   = 1.0

# --- Configurazione Logging ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Queue per la distanza ---
distance_queue = Queue()

def calculate_speed_fraction(distance: float) -> float:
    """
    Calcola la frazione di velocità in base alla distanza.
    """
    if distance < 0:
        return VELOCITY_OVER_3M_THRESHOLD
    elif distance < 0.5:
        return VELOCITY_THRESHOLD_0_5M
    elif 0.5 <= distance < 1.0:
        return VELOCITY_THRESHOLD_1M
    elif 1.0 <= distance < 2.0:
        return VELOCITY_2M_THRESHOLD
    elif 2.0 <= distance < 3.0:
        return VELOCITY_3M_THRESHOLD
    else:
        return VELOCITY_OVER_3M_THRESHOLD

def run_rtde_controller(stop_event: threading.Event):
    """
    Thread per il controllo del robot tramite RTDE.
    """
    con = None
    input_data = None
    current_distance = -1.0
    previous_speed_fraction = -1.0 # Variabile per memorizzare l'ultima velocità inviata

    # Il loop esterno gestisce i tentativi di riconnessione RTDE
    while not stop_event.is_set():
        try:
            logger.info("[RTDE_TX] Tentativo di connessione al robot UR...")
            con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
            
            # --- LOOP DI CONNESSIONE RTDE ---
            retries = 0
            MAX_RETRIES = 5 # Aumentato i tentativi per non disperarsi subito
            while not con.is_connected() and not stop_event.is_set():
                if retries >= MAX_RETRIES:
                    logger.error(f"[RTDE_TX] Impossibile connettersi dopo {MAX_RETRIES} tentativi. Riprovo la sequenza completa tra 10 secondi.")
                    raise ConnectionRefusedError("Connessione RTDE fallita ripetutamente")
                
                try:
                    con.connect()
                    if con.is_connected():
                        logger.info("[RTDE_TX] Connesso al robot.")
                        break # Esci dal loop di connessione se riuscito
                except Exception as e:
                    logger.warning(f"[RTDE_TX] Errore di connessione: {e}. Riprovo in 2 secondi...")
                time.sleep(2) # Pausa tra un tentativo e l'altro
                retries += 1

            if not con.is_connected():
                raise ConnectionRefusedError("Connessione RTDE non stabilita")

            conf = rtde_config.ConfigFile(CONFIG_XML)
            input_names, input_types = conf.get_recipe('in')
            output_names, output_types = conf.get_recipe('out')

            # --- ORDINE DI SETUP RTDE CRUCIALE ---
            # 1. Setup degli Input (questo è ciò che dovrebbe prendere il controllo dello slider)
            logger.debug("[RTDE_TX] Tentativo send_input_setup...")
            input_data = con.send_input_setup(input_names, input_types)
            if not input_data:
                logger.critical("[RTDE_TX] Errore configurazione input RTDE. Terminazione RTDE thread.")
                raise Exception("Errore configurazione input RTDE")
            logger.debug("[RTDE_TX] send_input_setup completato.")

            # Inizializza la maschera e la frazione dello slider nel pacchetto dati
            # Assicurati che questi attributi esistano sull'oggetto input_data
            if hasattr(input_data, 'speed_slider_mask'):
                input_data.speed_slider_mask = 1
            else:
                logger.warning("[RTDE_TX] 'speed_slider_mask' non trovato nella ricetta input. Impossibile controllare lo speed slider.")

            if hasattr(input_data, 'speed_slider_fraction'):
                input_data.speed_slider_fraction = VELOCITY_OVER_3M_THRESHOLD # Inizializza a 100%
            else:
                logger.warning("[RTDE_TX] 'speed_slider_fraction' non trovato nella ricetta input.")


            # 2. Setup degli Output
            logger.debug("[RTDE_TX] Tentativo send_output_setup...")
            if not con.send_output_setup(output_names, output_types, RTDE_FREQUENCY):
                logger.critical("[RTDE_TX] Fallita configurazione output RTDE. Terminazione RTDE thread.")
                raise Exception("Errore configurazione output RTDE")
            logger.debug("[RTDE_TX] send_output_setup completato.")

            # 3. Avvio della Sincronizzazione RTDE
            logger.debug("[RTDE_TX] Tentativo send_start...")
            if not con.send_start():
                logger.critical("[RTDE_TX] Fallita sincronizzazione RTDE (send_start). Terminazione RTDE thread.")
                raise Exception("Errore send_start RTDE")
            logger.info("[RTDE_TX] RTDE avviato e sincronizzato.")

            # --- LOOP PRINCIPALE DI COMUNICAZIONE RTDE ---
            while not stop_event.is_set() and con.is_connected():
                state = con.receive() # Riceve un pacchetto di stato dal robot
                if state:
                    # Legge l'ultima distanza disponibile dalla coda, svuotando le precedenti
                    try:
                        while not distance_queue.empty(): # Svuota la coda per prendere solo l'ultimo valore
                            current_distance = distance_queue.get_nowait()
                        # Qui, current_distance sarà l'ultimo valore messo nella coda, o il suo valore precedente se la coda era vuota
                    except Empty:
                        pass # La coda era vuota, usa l'ultimo current_distance conosciuto

                    # Calcola la nuova frazione di velocità in base alla distanza
                    new_speed_fraction = calculate_speed_fraction(current_distance)

                    # Invia la nuova frazione di velocità solo se è cambiata rispetto all'ultima inviata
                    if input_data and hasattr(input_data, 'speed_slider_fraction') and \
                       new_speed_fraction != previous_speed_fraction:
                        
                        input_data.speed_slider_fraction = new_speed_fraction
                        #con.send(input_data) # <--- INVIO DELLO SLIDER SPEED
                        previous_speed_fraction = new_speed_fraction # Aggiorna il valore per il confronto successivo
                        logger.info(f"[RTDE_TX] Distanza: {current_distance:.2f} m -> Velocità impostata: {new_speed_fraction*100:.0f}%")
                    
                    # Logga i dati del robot (es. velocità TCP) per debug
                    log_robot_data = f"[RTDE_RX] "
                    if hasattr(state, 'actual_TCP_speed'):
                        log_robot_data += f"Actual TCP Speed: {state.actual_TCP_speed} | "
                    if hasattr(state, 'target_TCP_speed'):
                        log_robot_data += f"Target TCP Speed: {state.target_TCP_speed}"
                    
                    #logger.debug(log_robot_data) # Abilita per un logging continuo dei dati del robot

                elif state is None:
                    # Questo accade se non ci sono dati disponibili nel buffer RTDE per la frequenza attuale.
                    # Non è necessariamente un errore di connessione, ma può indicare che la connessione è lenta
                    # o che il robot non sta inviando dati alla frequenza attesa.
                    logger.debug("[RTDE_TX] Nessun pacchetto RTDE ricevuto. Controlla connessione o frequenza.")
                
                # La pausa tra un ciclo e l'altro del loop RTDE è basata sulla frequenza
                time.sleep(1 / RTDE_FREQUENCY)

        except ConnectionRefusedError as e:
            logger.error(f"[RTDE_TX] Connessione al robot rifiutata o non stabilita: {e}. Riprovo tra 10s...")
            time.sleep(10) # Pausa più lunga prima di ritentare la connessione completa
        except Exception as e:
            logger.critical(f"[RTDE_TX] Errore critico nel thread RTDE: {e}. Riprovo la sequenza completa tra 5 secondi.", exc_info=True)
            time.sleep(5) # Pausa prima di ritentare la connessione dopo un errore generico
        finally:
            # Assicurati di disconnettere pulitamente in ogni caso
            if con and con.is_connected():
                try:
                    logger.info("[RTDE_TX] Invio send_pause prima della disconnessione.")
                    con.send_pause() # Importante per rilasciare i controlli
                    logger.info("[RTDE_TX] Disconnessione RTDE in corso.")
                    con.disconnect()
                    logger.info("[RTDE_TX] Connessione RTDE disconnessa con successo.")
                except Exception as e:
                    logger.warning(f"[RTDE_TX] Errore durante la disconnessione RTDE: {e}")
            con = None
            # Pausa significativa per dare tempo al robot di pulire lo stato
            logger.debug("[RTDE_TX] Pausa di 30 secondi prima di un nuovo tentativo di connessione RTDE.")
            time.sleep(30) # Aumentata la pausa qui per evitare riconnessioni troppo aggressive

    logger.info("[RTDE_TX] Thread RTDE terminato definitivamente.")

# --- La funzione main() ---
def main():
    stop_event = threading.Event()
    
    udp_process = None
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        udp_script_path = os.path.join(script_dir, "udp_listener.py")
        
        logger.info(f"Avvio del sottoprocesso UDP: {sys.executable} {udp_script_path}")
        # Modifica importante: bufsize=1 (line buffered) per garantire output riga per riga.
        # bufsize=0 è "unbuffered" e può causare problemi di performance o race conditions
        # quando si legge da pipe in tempo reale con readline(). bufsize=1 è meglio per text=True.
        udp_process = subprocess.Popen(
            [sys.executable, udp_script_path], 
            stdout=subprocess.PIPE,   
            stderr=subprocess.PIPE,   
            text=True,                
            bufsize=1, # Cambiato da 0 a 1 per line buffering               
            preexec_fn=os.setsid      
        )
        logger.info(f"Sottoprocesso UDP avviato con PID: {udp_process.pid}")
    except FileNotFoundError:
        logger.critical(f"Errore: File '{udp_script_path}' non trovato. Assicurati che esista e sia eseguibile.")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Errore nell'avvio del sottoprocesso UDP: {e}", exc_info=True)
        sys.exit(1)

    rtde_thread = threading.Thread(target=run_rtde_controller, args=(stop_event,), daemon=True)
    rtde_thread.start()

    logger.info("Premi 'q' e Invio per uscire.")

    poller = select.poll()
    poller.register(udp_process.stdout, select.POLLIN)
    poller.register(udp_process.stderr, select.POLLIN)
    poller.register(sys.stdin, select.POLLIN)

    try:
        while not stop_event.is_set():
            ready_fds = poller.poll(100) # Timeout aumentato a 100ms per ridurre il polling aggressivo

            for fd, event in ready_fds:
                if fd == udp_process.stdout.fileno():
                    line = udp_process.stdout.readline()
                    if line:
                        if line.startswith("DISTANCE:"):
                            try:
                                received_distance = float(line.strip().split(':')[1])
                                # L'uso del mutex non è necessario per queue.Queue, è già thread-safe.
                                # Rimuovi il blocco mutex per semplicità e per evitare potenziali blocchi.
                                # Rimuovi il loop while True per svuotare la coda qui.
                                # La coda dovrebbe essere svuotata nel thread consumer (RTDE).
                                # Qui si deve solo aggiungere l'ultimo valore.
                                distance_queue.put(received_distance) 
                                logger.debug(f"[MAIN_PROC] Distanza (PUT): {received_distance:.2f} m")
                            except ValueError:
                                logger.warning(f"[MAIN_PROC] Linea UDP malformata: {line.strip()}")
                        else:
                            logger.debug(f"[MAIN_PROC] Output UDP ignoto: {line.strip()}")
                elif fd == udp_process.stderr.fileno():
                    err_line = udp_process.stderr.readline()
                    if err_line:
                        logger.debug(f"[MAIN_PROC_UDP_ERR] {err_line.strip()}")
                elif fd == sys.stdin.fileno():
                    line = sys.stdin.readline().strip()
                    if line == 'q':
                        logger.info("Interruzione richiesta dall'utente. Chiusura in corso...")
                        stop_event.set()
                    else:
                        logger.info(f"Input ignorato: '{line}'. Premi 'q' per uscire.")

            if udp_process.poll() is not None:
                logger.error(f"Il sottoprocesso UDP è terminato inaspettatamente con codice: {udp_process.returncode}")
                # Leggi tutto l'stderr residuo in caso di crash per avere più info
                stderr_output = udp_process.stderr.read() 
                if stderr_output:
                    logger.error(f"Errore stderr residuo del sottoprocesso UDP:\n{stderr_output}")
                stop_event.set()
                break

    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera (Ctrl+C). Chiusura in corso...")
        stop_event.set()
    finally:
        logger.info("In attesa che i thread e i processi terminino...")
        time.sleep(0.1) # Breve pausa per evitare race condition minori
        
        # Gestione terminazione sottoprocesso UDP
        if udp_process and udp_process.poll() is None:
            logger.info("Invio segnale di terminazione al sottoprocesso UDP...")
            udp_process.terminate() # Invia SIGTERM
            try:
                udp_process.wait(timeout=2) # Attendi che termini graziosamente
            except subprocess.TimeoutExpired:
                logger.warning("Il sottoprocesso UDP non è terminato graziosamente, lo killo.")
                udp_process.kill() # Invia SIGKILL

        # Attendi la terminazione del thread RTDE
        rtde_thread.join(timeout=5)
        if rtde_thread.is_alive():
            logger.warning("Il thread RTDE non è terminato graziosamente entro il timeout.")

        logger.info("Tutti i componenti terminati. Programma concluso.")

if __name__ == "__main__":
    main()