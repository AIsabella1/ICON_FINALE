import requests #usato per effettuare richieste HTTP (per API)
import webbrowser   #usato per aprire automaticamente un URL nel browser
import secrets  #usato per generare stringhe casuali sicure (in PKCE)
import string   #usato per creare il code_verifier (PKCE)
from http.server import HTTPServer, BaseHTTPRequestHandler  #usato per creare il server locale per ricevere l'OAuth code
import urllib.parse #usato per costruire URL con parametri
import csv  #usato per scrivere e salvare file in formato CSV
import time #usato per gestire pause tra richieste (rate limiting)
import os   #usato per gestire percorsi e directory nel filesystem

#credenziali dell'applicazione, ottenute dal sito myanimelist.net/apiconfig
#ID dell'applicazione fornito da MAL
CLIENT_ID = '823135212a297d25238a81ee65b9e53b'
#secret key privata (tecnicamente da non condividere pubblicamente la lascio nel progetto cosi da poterlo utilizzare senza registrarsi)
CLIENT_SECRET = '5ce0b51e70b4df89c3bc9d9e7102755e46cb679150fc99cb4a0a95a6dd1cdbd1'
#URL dove ricevere la risposta OAuth
REDIRECT_URI = 'http://localhost:8080'

#crea un codice sicuro alfanumerico usato nel PKCE per proteggere lo scambio del token
def generate_code_verifier(length=64):
    chars = string.ascii_letters + string.digits + "-._~"
    return ''.join(secrets.choice(chars) for _ in range(length))

#server locale per catturare il codice di autorizzazione, quando MyAnimeList reindirizza al browser, questo handler intercetta la richiesta e salva il codice
class OAuthCallbackHandler(BaseHTTPRequestHandler):
    #valore condiviso per salvare il codice
    authorization_code = None
    def do_GET(self):
        #analizza l'URL della richiesta ricevuta dopo il login su MAL
        parsed_path = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_path.query)
        #estrae il parametro 'code'
        if 'code' in params:
            OAuthCallbackHandler.authorization_code = params['code'][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Autorizzazione completata. Chiudi questa finestra.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Errore codice mancante.</h1>")

#costruisce l’URL di autorizzazione e lo apre nel browser dell’utente
def open_authorization_url(code_verifier):
    auth_url = (f"https://myanimelist.net/v1/oauth2/authorize?"f"response_type=code&client_id={CLIENT_ID}&state=1234&"f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"f"code_challenge={code_verifier}&code_challenge_method=plain")
    print("\nSto aprendo il browser per autorizzare...")
    webbrowser.open(auth_url)

#scambio del codice per ottenere un token di accesso, fa una richiesta (una POST) per ottenere l'access token da MyAnimeList dopo l'autenticazione dell'utente
def get_access_token(auth_code, code_verifier):
    token_url = 'https://myanimelist.net/v1/oauth2/token'
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': REDIRECT_URI,
        'code_verifier': code_verifier
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0'
    }
    response = requests.post(token_url, data=data, headers=headers)
    if response.status_code == 200:
        print("Access Token ottenuto con successo.")
        return response.json()['access_token']
    else:
        print("Errore durante il recupero dell'access token:")
        print(response.status_code, response.text)
        return None

#salva i dati raccolti in un file CSV
def save_to_csv(manga_list, filename='dataset_ml.csv', folder='DATASET'):
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['ID', 'Titolo', 'Generi', 'Punteggio_Utente', 'Stato_Utente', 'Punteggio_Medio', 'Rank', 'Popolarita'])
        writer.writeheader()
        writer.writerows(manga_list)
    print(f"\nFile salvato: '{filepath}' con {len(manga_list)} manga.")

#effettua le richieste GET con retry
def request_with_retry(url, headers, params=None, max_retries=5):
    #tempo iniziale tra i retry
    delay = 2
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response
        elif response.status_code >= 500:
            print(f"Errore API: {response.status_code}, ritento tra {delay} secondi...")
            time.sleep(delay)
            #raddoppia il tempo di attesa a ogni tentativo
            delay *= 2  
        else:
            print(f"Errore API irreversibile: {response.status_code}")
            print(response.text)
            return response
    print("Numero massimo di tentativi raggiunto.")
    return None

#scarica la lista manga dell'utente con le info estese
def get_user_mangalist_extended(username, access_token, max_manga=25000):
    base_url = f'https://api.myanimelist.net/v2/users/{username}/mangalist'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    all_manga = []
    #limite massimo per richiesta
    limit = 100 
    fields = "id,title,genres,list_status{score,status}"

    #gestione dell'offset in caso di crash o interruzione
    offset_file = f'last_offset_{username}.txt'
    start_offset = 0
    if os.path.exists(offset_file):
        with open(offset_file, 'r') as f:
            start_offset = int(f.read().strip())

    for offset in range(start_offset, max_manga, limit):
        params = {
            'limit': limit,
            'offset': offset,
            'fields': fields
        }
        response = request_with_retry(base_url, headers, params)

        if not response or response.status_code != 200:
            break

        data = response.json().get('data', [])
        if not data:
            print(f"Fine dei dati a offset {offset}")
            break

        for entry in data:
            node = entry.get('node', {})
            list_status = entry.get('list_status', {})
            
            if not list_status:
                #ignora se non ci sono dati utente
                continue    

            user_status = list_status.get('status', '')
            if user_status == 'plan_to_read':
                #ignora i manga che l'utente vuole solo leggere in futuro
                continue    

            manga_id = node.get('id', '')
            title = node.get('title', '')
            genres_list = node.get('genres', [])
            genres = ", ".join([genre['name'] for genre in genres_list])
            score = list_status.get('score', '')

            #richiede i dati aggiuntivi per ogni manga (utile per ML)
            manga_extra_url = f'https://api.myanimelist.net/v2/manga/{manga_id}?fields=mean,rank,popularity'
            extra_response = request_with_retry(manga_extra_url, headers)

            if extra_response and extra_response.status_code == 200:
                extra_data = extra_response.json()
                mean_score = extra_data.get('mean', '')
                rank = extra_data.get('rank', '')
                popularity = extra_data.get('popularity', '')
            else:
                mean_score = ''
                rank = ''
                popularity = ''

            all_manga.append({'ID': manga_id,'Titolo': title,'Generi': genres,'Punteggio_Utente': score,'Stato_Utente': user_status,'Punteggio_Medio': mean_score,'Rank': rank,'Popolarita': popularity})
            
        print(f"Recuperati {len(data)} manga da offset {offset}")

        #salvataggio parziale e aggiornamento offset (utile in caso la connessione viene interrotta per qualche motivo)
        save_to_csv(all_manga, filename=f'temp_{username}.csv')
        with open(offset_file, 'w') as f:
            f.write(str(offset + limit))

        #aspetta 1 secondo tra le richieste per evitare rate-limit.
        time.sleep(1)   

    #rimuove il file di offset se il download è completato
    if os.path.exists(offset_file):
        os.remove(offset_file)

    print(f"\nTotale manga recuperati per {username}: {len(all_manga)}")
    return all_manga

#main
if __name__ == '__main__':
    username = input("Inserisci il tuo username di MyAnimeList: ")
    code_verifier = generate_code_verifier()
    open_authorization_url(code_verifier)
    print("Attesa autorizzazione...")

    #avvia il server HTTP per ricevere il codice OAuth
    with HTTPServer(('localhost', 8080), OAuthCallbackHandler) as httpd:
        httpd.handle_request()
    auth_code = OAuthCallbackHandler.authorization_code
    if auth_code:
        access_token = get_access_token(auth_code, code_verifier)
        if access_token:
            manga_data = get_user_mangalist_extended(username, access_token)
            save_to_csv(manga_data)
            
            #rimuove il file temporaneo se il download è completato
            temp_file = os.path.join('DATASET', f'temp_{username}.csv')
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"File temporaneo rimosso: {temp_file}")
                except Exception as e:
                    print(f"Impossibile eliminare il file temporaneo: {e}")
            else:
                print(f"File temporaneo non trovato: {temp_file}")
    else:
        print("Autorizzazione non completata.")