"""
Scraper AGATT - Cellule Appui Drone SDIS56
Utilise Playwright pour naviguer, cliquer et extraire les données complètes.
Lancer chaque matin à 6h via le Planificateur de tâches Windows.
"""

import json
import base64
import requests
from datetime import date, datetime
from playwright.sync_api import sync_playwright

# --- Configuration ---
import os
USERNAME = os.environ.get("AGATT_USER") or "Jlemarec"
PASSWORD = os.environ.get("AGATT_PASSWORD") or open(os.path.join(os.path.dirname(__file__), ".agatt_pwd")).read().strip() if os.path.exists(os.path.join(os.path.dirname(__file__), ".agatt_pwd")) else ""
LOGIN_URL = "https://agatt.sdis56.fr/public/index.php?c=204"
GITHUB_TOKEN = os.environ.get("AGATT_GITHUB_TOKEN") or open(os.path.join(os.path.dirname(__file__), ".agatt_token")).read().strip() if os.path.exists(os.path.join(os.path.dirname(__file__), ".agatt_token")) else ""
GITHUB_REPO = "julemarec56-dev/drone-planning"
GITHUB_FILE = "agatt_data.json"
OUTPUT_FILE = "agatt_data.json"

# Couleurs AGATT associées aux codes
COULEURS = {
    "rgb(51, 92, 204)":  "TPJ",
    "rgb(196, 0, 12)":   "TPN",
    "rgb(255, 204, 0)":  "OLJ",
    "rgb(102, 51, 153)": "OLN",
}


def get_planning():
    today = date.today()
    date_str = today.strftime("%Y%m%d")
    planning_url = f"https://agatt.sdis56.fr/register/index.php?a=gardeMois&d={date_str}&f={date_str}"

    result = {
        "date": today.isoformat(),
        "extracted_at": datetime.now().isoformat(),
        "TPJ": 0, "TPJ_noms": [],
        "TPN": 0, "TPN_noms": [],
        "OLJ": 0, "OLJ_noms": [],
        "OLN": 0, "OLN_noms": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Connexion
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Connexion à AGATT...")
        page.goto(LOGIN_URL)
        page.fill("input[name='login'], input[type='text']", USERNAME)
        page.fill("input[name='password'], input[type='password']", PASSWORD)
        page.evaluate("document.querySelector('form').submit()")
        page.wait_for_load_state("networkidle")

        if "Erreur de connexion" in page.content():
            raise Exception("Échec de connexion AGATT")

        # Planning du jour — sélectionner l'entité "Cellule appui drone" (id=1245)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Chargement du planning...")
        page.goto(planning_url)
        page.wait_for_load_state("networkidle")

        # Sélectionner la Cellule appui drone si ce n'est pas déjà fait
        current_centre = page.evaluate("() => document.getElementById('changerCentre')?.value || ''")
        if current_centre != "1245":
            page.select_option("#changerCentre", "1245")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

        # Cocher toutes les équipes (dont Accueil Cellule appui drone = for1245)
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
                const found = [];
                document.querySelectorAll('div, span').forEach(el => {
                    const txt = el.innerText?.trim();
                    if (!['TPJ','TPN','OLJ','OLN'].includes(txt)) return;
                    const bg = window.getComputedStyle(el).backgroundColor;
                    if (!COLORS[bg]) return;
                    let p = el.parentElement;
                    for (let i = 0; i < 25; i++) {
                        if (!p) break;
                        const lines = (p.innerText || '').split('\\n')
                            .map(l => l.trim()).filter(l => l.length > 3);
                        const nomLine = lines.find(l =>
                            /^[A-ZÉÈÊ\\-\\s]{2,20}\\s[A-Za-zéèêàâù]{2,10}$/.test(l)
                        );
                        if (nomLine && p.innerText.length < 300) {
                            found.push({ code: COLORS[bg], nom: nomLine });
                            break;
                        }
                        p = p.parentElement;
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
                                /^[A-ZÉÈÊ\\-\\s]{2,20}\\s[A-Za-zéèêàâù]{2,10}$/.test(l)
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


def main():
    try:
        data = get_planning()
        json_content = json.dumps(data, ensure_ascii=False, indent=2)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(json_content)
        print(f"[OK] {data['date']} — TPJ:{data['TPJ']} TPN:{data['TPN']} OLJ:{data['OLJ']} OLN:{data['OLN']}")
        for code in ["TPJ", "TPN", "OLJ", "OLN"]:
            if data[f"{code}_noms"]:
                print(f"     {code}: {', '.join(data[f'{code}_noms'])}")
        push_to_github(json_content)
    except Exception as e:
        print(f"[ERREUR] {e}")
        err = json.dumps({"date": date.today().isoformat(), "error": str(e)})
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(err)
        push_to_github(err)


if __name__ == "__main__":
    main()
