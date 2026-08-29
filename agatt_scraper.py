"""
Scraper AGATT - Cellule Appui Drone SDIS56
Utilise Playwright pour naviguer, cliquer et extraire les données complètes.
Lancer chaque matin à 6h via le Planificateur de tâches Windows.
"""

import json
import base64
import requests
import os
from datetime import date, datetime

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = r"C:\Users\julie\AppData\Local\ms-playwright"

from playwright.sync_api import sync_playwright
USERNAME = os.environ.get("AGATT_USER") or "Jlemarec"
PASSWORD = os.environ.get("AGATT_PASSWORD") or open(os.path.join(os.path.dirname(__file__), ".agatt_pwd")).read().strip() if os.path.exists(os.path.join(os.path.dirname(__file__), ".agatt_pwd")) else ""
LOGIN_URL = "https://agatt.sdis56.fr/public/index.php?c=204"
GITHUB_TOKEN = os.environ.get("AGATT_GITHUB_TOKEN") or open(os.path.join(os.path.dirname(__file__), ".agatt_token")).read().strip() if os.path.exists(os.path.join(os.path.dirname(__file__), ".agatt_token")) else ""
GITHUB_REPO = "julemarec56-dev/drone-planning"
# Repo de la page fusionnée "Cellule Appui Drone" (Astreinte + Météo) — publication
# additionnelle, en plus de GITHUB_REPO ci-dessus, sans rien changer à celui-ci.
GITHUB_REPO_MERGED = "julemarec56-dev/cellule-appui-drone"
GITHUB_FILE = "agatt_data.json"
OUTPUT_FILE = "agatt_data.json"

# Couleurs AGATT associées aux codes
COULEURS = {
    "rgb(51, 92, 204)":  "TPJ",
    "rgb(196, 0, 12)":   "TPN",
    "rgb(255, 204, 0)":  "OLJ",
    "rgb(102, 51, 153)": "OLN",
}


def get_planning(target_date=None):
    import time
    MAX_RETRIES = 3

    today = target_date or date.today()
    date_str = today.strftime("%Y%m%d")
    planning_url = f"https://agatt.sdis56.fr/register/index.php?a=gardeMois&d={date_str}&f={date_str}"

    last_error = None
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait_s = attempt * 20
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Tentative {attempt+1}/{MAX_RETRIES} après erreur, attente {wait_s}s...")
            time.sleep(wait_s)
        try:
            return _get_planning_once(today, planning_url)
        except Exception as e:
            last_error = e
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Échec tentative {attempt+1}: {e}")

    raise last_error


def _get_planning_once(today, planning_url):
    result = {
        "date": today.isoformat(),
        "extracted_at": datetime.now().isoformat(),
        "TPJ": 0, "TPJ_noms": [],
        "TPN": 0, "TPN_noms": [],
        "OLJ": 0, "OLJ_noms": [],
        "OLN": 0, "OLN_noms": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page()

        # Connexion
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Connexion à AGATT...")
        page.goto(LOGIN_URL)
        page.fill("input[name='login'], input[type='text']", USERNAME)
        page.fill("input[name='password'], input[type='password']", PASSWORD)
        page.evaluate("document.querySelector('form').submit()")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        if "Erreur de connexion" in page.content():
            raise Exception("Échec de connexion AGATT")

        # Planning du jour — sélectionner l'entité "Cellule appui drone" (id=1244)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Chargement du planning...")
        page.goto(planning_url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Sélectionner la Cellule appui drone.
        # AGATT a changé l'id du centre (1245 -> 1244 le 27/08/2026) : on sélectionne
        # par id connu, puis par libellé en repli si l'id n'existe plus.
        CENTRE_ID = "1244"
        current_centre = page.evaluate(
            "() => document.getElementById('changerCentre')?.value || ''"
        )
        if current_centre != CENTRE_ID:
            forced = page.evaluate("""
                (wanted) => {
                    const sel = document.getElementById('changerCentre');
                    if (!sel) return 'no-select';
                    let opt = Array.from(sel.options).find(o => o.value === wanted);
                    if (!opt) opt = Array.from(sel.options).find(o => /cellule appui drone/i.test(o.text));
                    if (!opt) return 'option-introuvable';
                    sel.value = opt.value;
                    if (window.$ && $('#changerCentre').length) {
                        $('#changerCentre').val(opt.value).trigger('change');
                    } else {
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        if (typeof changementCentre === 'function') changementCentre(sel.form);
                    }
                    return 'changed->' + opt.value;
                }
            """, CENTRE_ID)
            log(f"Centre change: {current_centre} -> {CENTRE_ID} ({forced})")
            if forced == 'option-introuvable':
                raise Exception("Option 'Cellule appui drone' introuvable dans le menu des centres")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
        else:
            log(f"Centre déjà {CENTRE_ID}, pas de changement")

        # Cocher toutes les équipes (dont Accueil Cellule appui drone = for1244)
        cochees = page.evaluate("""
            () => {
                let count = 0;
                document.querySelectorAll('input[type=checkbox]').forEach(cb => {
                    if (!cb.checked && (cb.id.startsWith('for') || cb.name.startsWith('checkbox'))) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change'));
                        count++;
                    }
                });
                // Cliquer sur AFFICHER
                const btns = Array.from(document.querySelectorAll('input[type=button], input[type=submit], button'));
                const btn = btns.find(b => (b.value || b.innerText || '').toUpperCase().includes('AFFICHER'));
                if (btn) { btn.click(); return count; }
                return count;
            }
        """)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {cochees} équipe(s) supplémentaire(s) cochée(s).")

        # Extraire les codes colorés + noms d'agents (JS validé en session)
        agents_codes = page.evaluate("""
            () => {
                const COLORS = {
                    'rgb(51, 92, 204)':  'TPJ',
                    'rgb(196, 0, 12)':   'TPN',
                    'rgb(255, 204, 0)':  'OLJ',
                    'rgb(102, 51, 153)': 'OLN'
                };
                const NOM_RE = /^[A-ZÀÂÉÈÊËÎÏÔÙÛÜŸÆŒÇ\\-\\s]{2,20}\\s[A-Za-zàâéèêëîïôùûüÿæœç]{2,10}$/;

                function trouverNom(el) {
                    let p = el.parentElement;
                    for (let i = 0; i < 25; i++) {
                        if (!p) break;
                        const lines = (p.innerText || '').split('\\n')
                            .map(l => l.trim()).filter(l => l.length > 3);
                        const nomLine = lines.find(l => NOM_RE.test(l));
                        if (nomLine && p.innerText.length < 300) return nomLine;
                        p = p.parentElement;
                    }
                    return null;
                }

                const found = [];

                // 1. Badges colores standards (bleu TPJ, rouge TPN, jaune OLJ, violet OLN)
                // Badge peut etre composite (ex. "CG" + "OLN") : on cherche si le texte contient le code.
                document.querySelectorAll('div, span').forEach(el => {
                    const txt = el.innerText?.trim();
                    if (!txt) return;
                    const bg = window.getComputedStyle(el).backgroundColor;
                    if (!COLORS[bg]) return;
                    // Le code de rôle est le fragment reconnu dans le texte
                    const code = ['TPJ','TPN','OLJ','OLN'].find(c => txt === c || txt.includes(c));
                    if (!code) return;
                    const nom = trouverNom(el);
                    if (nom) found.push({ code: COLORS[bg], nom });
                });

                // 2. Badges "AsJ"/"AsN" : Astreinte Jour/Nuit drone
                //    → code déterminé par la qualification TP ou OL dans le même bloc de ligne (< 150 chars)
                document.querySelectorAll('div, span').forEach(el => {
                    const txt = el.innerText?.trim();
                    if (!['AsJ','AsN','AsP'].includes(txt)) return;
                    const nom = trouverNom(el);
                    if (!nom) return;
                    // Chercher la qualification "TP" ou "OL" dans un bloc suffisamment petit
                    // pour être la même ligne de tableau (pas un parent qui contient toute la liste)
                    let p = el.parentElement;
                    let qualif = null;
                    for (let i = 0; i < 10; i++) {
                        if (!p) break;
                        if (p.innerText.length < 150) {
                            const lines = p.innerText.split('\\n').map(l => l.trim());
                            if (lines.includes('TP')) { qualif = 'TP'; break; }
                            if (lines.includes('OL')) { qualif = 'OL'; break; }
                        }
                        p = p.parentElement;
                    }
                    if (qualif === 'TP') {
                        if (txt === 'AsJ' || txt === 'AsP') found.push({ code: 'TPJ', nom });
                        if (txt === 'AsN' || txt === 'AsP') found.push({ code: 'TPN', nom });
                    } else if (qualif === 'OL') {
                        if (txt === 'AsJ' || txt === 'AsP') found.push({ code: 'OLJ', nom });
                        if (txt === 'AsN' || txt === 'AsP') found.push({ code: 'OLN', nom });
                    }
                });

                return found;
            }
        """)

        # Cliquer sur chaque cellule colorée pour révéler le popup complet
        clicked_agents = {}
        cells = page.locator("div, span").all()

        for el in cells:
            try:
                txt = el.inner_text(timeout=200).strip()
                if txt not in ["TPJ", "TPN", "OLJ", "OLN"]:
                    continue
                bg = el.evaluate("el => window.getComputedStyle(el).backgroundColor")
                if bg not in COULEURS:
                    continue

                nom = el.evaluate("""
                    el => {
                        let p = el.parentElement;
                        for (let i = 0; i < 25; i++) {
                            if (!p) break;
                            const lines = (p.innerText || '').split('\\n')
                                .map(l => l.trim()).filter(l => l.length > 3);
                            const nomLine = lines.find(l =>
                                /^[A-ZÀÂÉÈÊËÎÏÔÙÛÜŸÆŒÇ\\-\\s]{2,20}\\s[A-Za-zàâéèêëîïôùûüÿæœç]{2,10}$/.test(l)
                            );
                            if (nomLine && p.innerText.length < 300) return nomLine;
                            p = p.parentElement;
                        }
                        return null;
                    }
                """)
                if not nom:
                    continue

                el.click()
                page.wait_for_timeout(500)

                # Lire le popup AGATT (fenêtre x-window)
                popup_text = page.evaluate("""
                    () => {
                        const sel = [
                            '.x-window-body', '.x-window', '[class*="x-win"]',
                            '[class*="popup"]', '[class*="detail"]', '[class*="tooltip"]'
                        ].join(', ');
                        const p = document.querySelector(sel);
                        return p ? p.innerText : '';
                    }
                """)

                page.keyboard.press("Escape")
                page.wait_for_timeout(300)

                if nom not in clicked_agents:
                    clicked_agents[nom] = set()

                if popup_text:
                    if "Télépilote Jour" in popup_text:
                        clicked_agents[nom].add("TPJ")
                    if "Télépilote Nuit" in popup_text:
                        clicked_agents[nom].add("TPN")
                    if "liaison Jour" in popup_text:
                        clicked_agents[nom].add("OLJ")
                    if "liaison Nuit" in popup_text:
                        clicked_agents[nom].add("OLN")
                else:
                    clicked_agents[nom].add(COULEURS[bg])

            except Exception:
                continue

        # Fallback : utiliser les codes colorés directs si aucun popup trouvé
        if not clicked_agents:
            for item in agents_codes:
                nom = item["nom"]
                code = item["code"]
                if nom not in clicked_agents:
                    clicked_agents[nom] = set()
                clicked_agents[nom].add(code)

        # Indicateurs numériques depuis le bas de page (utilise includes pour gérer l'encodage)
        indicateurs = page.evaluate("""
            () => {
                const res = { TPJ: null, TPN: null, OLJ: null, OLN: null };
                const txt = document.body.innerText;
                const lines = txt.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                const map = [
                    ['pilotes Jour', 'TPJ'],
                    ['pilotes Nuit', 'TPN'],
                    ['liaison Jour', 'OLJ'],
                    ['liaison Nuit', 'OLN']
                ];
                for (let i = 0; i < lines.length; i++) {
                    for (const [fragment, code] of map) {
                        if (lines[i].includes(fragment)) {
                            for (let j = i+1; j <= i+3; j++) {
                                const val = parseInt(lines[j]);
                                if (!isNaN(val) && val >= 0 && val <= 99) {
                                    res[code] = val;
                                    break;
                                }
                            }
                        }
                    }
                }
                return res;
            }
        """)

        browser.close()

        # Construire le résultat final
        for nom, codes in clicked_agents.items():
            for code in codes:
                if nom not in result[f"{code}_noms"]:
                    result[f"{code}_noms"].append(nom)

        # Indicateurs numériques depuis la page (source de vérité)
        for code in ["TPJ", "TPN", "OLJ", "OLN"]:
            val_page = indicateurs.get(code)
            result[code] = val_page if val_page is not None else (1 if result[f"{code}_noms"] else 0)
            # Caler la liste sur l'indicateur : 0 → vide, N → garder les N premiers noms
            # (les badges colorés standards sont ajoutés avant les badges AsJ/AsN, donc prioritaires)
            if result[code] == 0:
                result[f"{code}_noms"] = []
            elif len(result[f"{code}_noms"]) > result[code]:
                result[f"{code}_noms"] = result[f"{code}_noms"][:result[code]]

        # Si TPN=1 mais aucun nom TPN trouvé (cas AsP = astreinte permanence jour+nuit)
        # → le télépilote de jour couvre aussi la nuit
        if result["TPN"] == 1 and not result["TPN_noms"] and result["TPJ_noms"]:
            result["TPN_noms"] = result["TPJ_noms"][:]

        # Même logique pour OLN si besoin
        if result["OLN"] == 1 and not result["OLN_noms"] and result["OLJ_noms"]:
            result["OLN_noms"] = result["OLJ_noms"][:]

    return result


def push_to_github(json_content):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "agatt-scraper"}
    r = requests.get(api_url, headers=headers, verify=False)
    sha = r.json().get("sha") if r.status_code == 200 else None
    content_b64 = base64.b64encode(json_content.encode("utf-8")).decode("utf-8")
    body = {"message": f"planning {date.today().isoformat()}", "content": content_b64}
    if sha:
        body["sha"] = sha
    resp = requests.put(api_url, headers=headers, json=body, verify=False)
    if resp.status_code in (200, 201):
        print("[OK] JSON publié sur GitHub Pages")
    else:
        print(f"[ERREUR GitHub] {resp.status_code} - {resp.text[:200]}")


def attendre_reseau(timeout=60):
    """Attend que le réseau soit disponible avant de commencer."""
    import time, socket
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Vérification réseau...")
    for _ in range(timeout):
        try:
            socket.setdefaulttimeout(3)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Réseau disponible.")
            return True
        except Exception:
            time.sleep(1)
    print("[ERREUR] Réseau non disponible après 60s.")
    return False


SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK") or (
    open(os.path.join(os.path.dirname(__file__), ".slack_webhook")).read().strip()
    if os.path.exists(os.path.join(os.path.dirname(__file__), ".slack_webhook")) else ""
)
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper_log.txt")
GITHUB_FILE_DEMAIN = "agatt_data_demain.json"

CODES = {
    "TPJ": "Télépilote Jour",
    "TPN": "Télépilote Nuit",
    "OLJ": "Officier de Liaison Jour",
    "OLN": "Officier de Liaison Nuit",
}

JOURS_FR = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
MOIS_FR = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]


def log(msg):
    ligne = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(ligne)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def date_fr(d):
    return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month-1]} {d.year}"


def bloc_planning(data, label):
    d = date.fromisoformat(data["date"])
    lignes = [f"*{label}, {date_fr(d)}*"]
    manquants = []
    for code in ["TPJ", "TPN", "OLJ", "OLN"]:
        ok = data[code] >= 1
        noms = ", ".join(data[f"{code}_noms"]) if data[f"{code}_noms"] else "POSTE VACANT :warning:"
        icone = "✅" if ok else "❌"
        lignes.append(f"{icone} {CODES[code]} : {noms}")
        if not ok:
            manquants.append(CODES[code])
    if manquants:
        lignes.append(f"\n:rotating_light: *Manquement{'s' if len(manquants)>1 else ''} : {', '.join(manquants)}*")
    return "\n".join(lignes)


def push_json_github(json_content, filename, repo=None):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    repo = repo or GITHUB_REPO
    api_url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "agatt-scraper"}
    r = requests.get(api_url, headers=headers, verify=False)
    sha = r.json().get("sha") if r.status_code == 200 else None
    content_b64 = base64.b64encode(json_content.encode("utf-8")).decode("utf-8")
    body = {"message": f"planning {filename}", "content": content_b64}
    if sha:
        body["sha"] = sha
    resp = requests.put(api_url, headers=headers, json=body, verify=False)
    if resp.status_code not in (200, 201):
        log(f"[ERREUR GitHub {repo}] {resp.status_code} - {resp.text[:200]}")
    return resp.status_code in (200, 201)


def main():
    log("=== DEBUT SCRAPER ===")
    attendre_reseau()
    try:
        from datetime import timedelta
        today = date.today()
        demain = today + timedelta(days=1)

        # Scraper aujourd'hui
        log("Scraping aujourd'hui...")
        data_auj = get_planning(today)
        json_auj = json.dumps(data_auj, ensure_ascii=False, indent=2)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(json_auj)
        push_json_github(json_auj, GITHUB_FILE)
        push_json_github(json_auj, GITHUB_FILE, repo=GITHUB_REPO_MERGED)
        log(f"[OK] Aujourd'hui — TPJ:{data_auj['TPJ']} TPN:{data_auj['TPN']} OLJ:{data_auj['OLJ']} OLN:{data_auj['OLN']}")

        # Scraper demain
        log("Scraping demain...")
        data_dem = get_planning(demain)
        json_dem = json.dumps(data_dem, ensure_ascii=False, indent=2)
        push_json_github(json_dem, GITHUB_FILE_DEMAIN)
        push_json_github(json_dem, GITHUB_FILE_DEMAIN, repo=GITHUB_REPO_MERGED)
        log(f"[OK] Demain — TPJ:{data_dem['TPJ']} TPN:{data_dem['TPN']} OLJ:{data_dem['OLJ']} OLN:{data_dem['OLN']}")

        # Slack récapitulatif
        texte = (
            ":clipboard: *RÉCAPITULATIF PLANNING DRONE*\n\n"
            + bloc_planning(data_auj, "Aujourd'hui")
            + "\n\n"
            + bloc_planning(data_dem, "Demain")
        )
        if SLACK_WEBHOOK:
            requests.post(SLACK_WEBHOOK, json={"text": texte}, verify=False)
            log("[OK] Slack envoyé")

    except Exception as e:
        import traceback
        log(f"[ERREUR] {e}\n{traceback.format_exc()}")
        if SLACK_WEBHOOK:
            requests.post(SLACK_WEBHOOK, json={"text": f":x: *Erreur scraper AGATT* — {str(e)[:150]}"}, verify=False)


if __name__ == "__main__":
    main()
