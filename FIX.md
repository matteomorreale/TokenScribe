# FIX

Audit ponytail del repo. Stato: `[ ]` da fare, `[x]` fatto.

## Must fix

- [x] **1. Console di debug aperta sulla rete** (`run.py:L20-22`)
  Senza `FLASK_ENV` vale `development`: `debug=True` su `0.0.0.0`. La console Werkzeug esegue codice Python, e senza login chiunque in rete può anche lanciare run a pagamento o cancellare i dati.
  Fix: host di default `127.0.0.1`, debug solo con `TOKENSCRIBE_DEBUG=1`.

- [ ] **2. Nessuna protezione CSRF** (`settings_controller.py`: `/reset-db`, `/api-keys`)
  Un'altra pagina aperta nel browser può inviare un POST con `confirm_reset=RESET` e cancellare il database, o sostituire le chiavi API.
  Fix: token CSRF su tutti i POST (Flask-WTF `CSRFProtect`) o controllo dell'header `Origin` in un `before_request`.

- [x] **3. Il worker dorme 2 s anche con la coda piena** (`queue_model.py:L65-98`, `queue_service.py:L118-120`)
  20 thread leggono la stessa riga in cima, uno vince, gli altri 19 ricevono `None` e dormono 2 s credendo la coda vuota.
  Fix: claim in un solo `UPDATE ... RETURNING` (SQLite >= 3.35).

- [x] **4. Il timeout non ferma niente, e crea risultati doppi** (`queue_service.py:L138-147`, `llm_service.py`)
  Il `with ThreadPoolExecutor` aspetta la fine della chiamata anche dopo il timeout, e i client SDK non hanno `timeout=`. Il worker resta bloccato fino a ~10 minuti. La chiamata orfana poi scrive il suo risultato, e il retry ne scrive un secondo (`token_results` non ha vincoli di unicità).
  Fix: `timeout=` sui client SDK, `max_retries=0` come già fatto per Anthropic, e non aspettare l'orfano.

## Should fix

- [ ] **5. Con il reloader due processi usano la stessa coda** (`app/__init__.py:L52-55`, `run.py:L17`)
  Con `debug=True` `create_app` gira nel padre e nel figlio: 40 worker. Il figlio chiama `recover_stale_running()` e rimette a `pending` gli item in corso nel padre, che partono due volte.
  Fix: avviare la coda solo se `WERKZEUG_RUN_MAIN == "true"` o se il reloader è spento. Il punto 1 riduce già il problema.

- [ ] **6. Il reset cancella le tabelle mentre i worker lavorano** (`database.py:L889-903`)
  Una scrittura a metà reset può fallire, e le chiavi API (tabella `settings`) vanno perse.
  Fix: rifiutare il reset se ci sono item `running`, e avvisare nel form che le chiavi vengono cancellate.

- [ ] **7. Mancano i test per coda, cifratura e reset** (`tests/`)
  Serve un test per il claim concorrente (due thread, item diversi) e uno per `CryptoService.decrypt` con chiave sbagliata.

- [ ] **8. `SECRET_KEY` ha un default noto** (`config.py:L13`)
  Oggi firma solo i `flash`. Con login o sessioni diventerebbe falsificabile.
  Fix: in `ProductionConfig`, non partire se la variabile manca.

## Nice to have

- [ ] **9. Logo duplicato** (`tokenscribe-logo.jpg` e `app/static/img/tokenscribe-logo.jpg`)
  Tenere una copia sola e puntare il README a `app/static/img/`. Verificare prima con `cmp`.

- [ ] **10. Liste `IN (?, ?, ...)` senza limite** (`experiment_model.py:L216`, `queue_model.py:L322, L461`, `selection_score_model.py:L116`)
  Le query sono parametrizzate, ma SQLite ha un tetto sul numero di variabili. Spezzare in blocchi da 500 solo se i run superano le migliaia di item.

## Non verificato

`llm_service.py` (lettura parziale), `magi_service.py`, `calibration_service.py`, `scoring_service.py`, `translation_ai_service.py` e i template Jinja non sono stati letti a fondo. Il punto 5 viene dalla lettura del codice e non è stato riprodotto.
