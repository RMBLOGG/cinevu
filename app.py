from flask import Flask, render_template, request, jsonify, redirect, url_for
from bs4 import BeautifulSoup
import requests, re, os

app = Flask(__name__)

BASE_URL = "https://breezyandaman.com"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": BASE_URL,
}

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"Error: {e}")
    return None

def txt(el):
    return el.get_text(strip=True) if el else ""

def best_poster(img):
    import re as _re
    if not img:
        return ""
    # Ambil semua URL dari srcset, pilih yang terbesar (terakhir)
    srcset = img.get("srcset", "")
    srcs = [s.strip().split(" ")[0] for s in srcset.split(",") if s.strip()]
    url = srcs[-1] if srcs else (img.get("data-src") or img.get("src") or "")
    # Hapus suffix dimensi WordPress (-152x228, -60x90, dll) → gambar full size
    url = _re.sub(r"-\d+x\d+(\.[a-zA-Z]+)$", r"\1", url)
    return url

def clean_title(raw):
    if not raw:
        return ""
    # Hapus prefix "Permalink to: "
    raw = re.sub(r'^Permalink to\s*:\s*', '', raw, flags=re.I)
    return raw.strip()

def parse_cards(soup):
    movies = []
    for art in soup.find_all("article"):
        a = art.find("a", href=True)
        if not a:
            continue
        # Prioritas: heading tag > img alt > link title (bersihkan "Permalink to:")
        heading = art.find(re.compile(r"h\d"))
        title = txt(heading) if heading else ""
        if not title:
            img = art.find("img")
            title = img.get("alt","").strip() if img else ""
        if not title:
            title = clean_title(a.get("title",""))
        item = {
            "url":      a["href"],
            "title":    title,
            "poster":   best_poster(art.find("img")),
            "rating":   txt(art.find(class_="gmr-rating-item")).strip(),
            "quality":  txt(art.find(class_="gmr-quality-item")),
            "duration": txt(art.find(class_="gmr-duration-item")),
            "episodes": txt(art.find(class_="gmr-numbeps")).replace("Eps:","").strip(),
        }
        if item["url"] and item["title"]:
            movies.append(item)
    return movies

def get_next_page(soup):
    nxt = soup.find("a", class_=re.compile(r"next", re.I))
    return nxt["href"] if nxt else None

def parse_detail(url):
    soup = get_soup(url)
    if not soup:
        return None
    data = {"url": url}
    t = soup.find("h1", class_="entry-title")
    data["title"] = txt(t)
    thumb = soup.find("div", class_="single-thumb")
    data["poster"] = best_poster(thumb.find("img") if thumb else None) or best_poster(soup.find("img", class_="wp-post-image"))
    data["rating"] = txt(soup.find("span", itemprop="ratingValue"))
    data["rating_count"] = txt(soup.find("span", itemprop="ratingCount"))
    syn_div = soup.find("div", class_="entry-content-single")
    if syn_div:
        paras = [p.get_text(strip=True) for p in syn_div.find_all("p") if len(p.get_text(strip=True)) > 40]
        data["synopsis"] = " ".join(paras[:3])
    else:
        data["synopsis"] = ""
    meta = {}
    for div in soup.find_all("div", class_="gmr-moviedata"):
        strong = div.find("strong")
        if not strong:
            continue
        label = txt(strong).rstrip(":").lower()
        links = [txt(a) for a in div.find_all("a")]
        if links:
            meta[label] = ", ".join(links)
        else:
            spans = [txt(el) for el in div.find_all(["span","time"]) if txt(el)]
            meta[label] = ", ".join(spans) if spans else div.get_text(strip=True).replace(txt(strong),"").strip()
    data["meta"] = meta
    sw = soup.find(id="muvipro_player_content_id")
    data["post_id"] = sw.get("data-id") if sw else None
    trailer = soup.find("a", class_="gmr-trailer-popup")
    data["trailer"] = trailer["href"] if trailer else None
    episodes = []
    ep_div = soup.find("div", class_="gmr-listseries")
    if ep_div:
        for a in ep_div.find_all("a", class_="button"):
            episodes.append({"label": txt(a), "url": a.get("href",""), "title": a.get("title","")})
    data["episodes"] = episodes
    # Related
    related = []
    for sec in soup.find_all("div", class_="gmr-box-content"):
        for art in sec.find_all("article")[:8]:
            m = parse_cards(BeautifulSoup(str(art), "html.parser"))
            related.extend(m)
    data["related"] = related[:8]
    return data

def get_players(post_id):
    session = requests.Session()
    session.headers.update(HEADERS)
    players = []
    for tab in ["p1","p2","p3","p4"]:
        try:
            r = session.post(AJAX_URL, data={"action":"muvipro_player_content","tab":tab,"post_id":post_id}, timeout=10)
            if r.status_code == 200 and r.text.strip():
                inner = BeautifulSoup(r.text, "html.parser")
                iframe = inner.find("iframe")
                if iframe:
                    src = iframe.get("src") or iframe.get("SRC") or ""
                    if src:
                        players.append({"server": tab.upper(), "url": src})
        except:
            pass
    return players

# ── Routes ──

@app.route("/")
def home():
    page = request.args.get("page", "1")

    def fetch(url):
        s = get_soup(url)
        return parse_cards(s)[:12] if s else []

    if page == "1":
        sections = [
            {"id": "terbaru",  "title": "Film Terbaru",    "url": f"{BASE_URL}/",                          "more": "/?page=2"},
            {"id": "trending", "title": "Trending",         "url": f"{BASE_URL}/category/trending/",        "more": "/genre/trending"},
            {"id": "series",   "title": "Series & TV Show", "url": f"{BASE_URL}/tv/",                       "more": "/series"},
            {"id": "anime",    "title": "Anime",             "url": f"{BASE_URL}/category/animation/anime/","more": "/anime"},
            {"id": "action",   "title": "Action",            "url": f"{BASE_URL}/category/action/",         "more": "/genre/action"},
            {"id": "horror",   "title": "Horror",            "url": f"{BASE_URL}/category/horror/",         "more": "/genre/horror"},
            {"id": "korea",    "title": "Film Korea",        "url": f"{BASE_URL}/country/korea/",           "more": "/country/korea"},
            {"id": "indo",     "title": "Film Indonesia",    "url": f"{BASE_URL}/country/indonesia/",       "more": "/country/indonesia"},
            {"id": "semi",     "title": "Film Semi",         "url": f"{BASE_URL}/category/film-semi/",      "more": "/semi"},
        ]
        for sec in sections:
            sec["movies"] = fetch(sec["url"])
        return render_template("home.html", sections=sections, page=1, active="home")
    else:
        url = f"{BASE_URL}/page/{page}/"
        soup = get_soup(url)
        movies = parse_cards(soup) if soup else []
        next_page = get_next_page(soup) if soup else None
        return render_template("list.html", movies=movies, page=int(page), title="Film Terbaru", next_page=next_page, active="home")

@app.route("/series")
def series():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/tv/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Series", next_page=get_next_page(soup), active="series")

@app.route("/anime")
def anime():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/animation/anime/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Anime", next_page=get_next_page(soup), active="anime")

@app.route("/semi")
def semi():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/film-semi/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Film Semi", next_page=get_next_page(soup), active="semi")

@app.route("/genre/<slug>")
def genre(slug):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/{slug}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=slug.replace("-"," ").title(), next_page=get_next_page(soup), active="")

@app.route("/year/<year>")
def by_year(year):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/year/{year}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=f"Film Tahun {year}", next_page=get_next_page(soup), active="")

@app.route("/country/<country>")
def by_country(country):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/country/{country}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=country.title(), next_page=get_next_page(soup), active="")

@app.route("/search")
def search():
    q = request.args.get("q", "")
    page = request.args.get("page", "1")
    if not q:
        return redirect(url_for("home"))
    url = f"{BASE_URL}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    if page != "1":
        url = f"{BASE_URL}/page/{page}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=f'Hasil: "{q}"', next_page=get_next_page(soup), active="", query=q)

@app.route("/watch")
def watch():
    url = request.args.get("url", "")
    if not url:
        return redirect(url_for("home"))
    data = parse_detail(url)
    if not data:
        return redirect(url_for("home"))
    return render_template("watch.html", movie=data, active="")

@app.route("/api/player")
def api_player():
    post_id = request.args.get("post_id", "")
    if not post_id:
        return jsonify({"error": "post_id required"}), 400
    players = get_players(post_id)
    return jsonify({"players": players})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
