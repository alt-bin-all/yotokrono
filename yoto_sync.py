#!/usr/bin/env python3
import urllib.request
import re
import html
import os
import subprocess
import sys

def run_sys_command(cmd):
    """Helper to safely execute local shell commands."""
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Error executing command: {cmd}\n{result.stderr}")
        return False
    return True

def sanitize_folder_name(name):
    """Converts a podcast title into a safe web-facing directory path."""
    name = re.sub(r'[^\w\s-]', '', name).strip().lower()
    return re.sub(r'[-\s]+', '_', name)

def clean_yoto_url(raw_url):
    """
    Strips out tracking redirects (like mgln.ai and pscrb.fm) and tracking query tokens
    to provide the direct raw MP3 asset link that Yoto requires.
    """
    # 1. Look for the real hidden URL inside the redirection chain
    match = re.search(r'(https://rss\.art19\.com/episodes/[a-f0-8-]+/?[^?\s"]*)', raw_url)
    if match:
        clean_url = match.group(1)
    else:
        # 2. Fallback: just strip out query strings if the pattern is different
        clean_url = raw_url.split('?')[0]
    
    # 3. Ensure it strictly ends with .mp3 or similar clean extension
    if not clean_url.endswith('.mp3'):
        # If the tracking removal trimmed the extension, put it back
        clean_url = re.sub(r'(\.mp3).*$', r'\1', clean_url)
        
    return clean_url

def auto_sync_podcast(feed_url):
    print(f"[*] Fetching feed payload from: {feed_url}")
    
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            feed_data = response.read().decode("utf-8")
    except Exception as e:
        print(f"[-] Network connection error: {e}")
        sys.exit(1)

    show_title_match = re.search(r"<title>(.*?)</title>", feed_data, re.DOTALL)
    if not show_title_match:
        print("[-] Critical Error: Could not determine overall Show Title from feed.")
        sys.exit(1)
        
    show_folder = sanitize_folder_name(show_title_match.group(1))
    print(f"[+] Targeting path destination: ./{show_folder}/")
    os.makedirs(show_folder, exist_ok=True)

    items = feed_data.split("<item>")[1:]
    items.reverse()  # Chronological order
    print(f"[+] Extracted {len(items)} audio items total.")

    parsed_tracks = []
    for item in items:
        title_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        url_match = re.search(r'<enclosure[^>]*url="([^"]+)"', item)
        season_match = re.search(r'<itunes:season>(\d+)</itunes:season>', item)
        
        if not url_match or not title_match:
            continue
            
        title = title_match.group(1).strip()
        
        # Apply the tracking cleaner here
        mp3_url = clean_yoto_url(url_match.group(1).strip())
        
        if season_match:
            s_id = season_match.group(1)
        else:
            title_s_match = re.search(r"\bS(\d+)\s*E\d+", title, re.IGNORECASE)
            s_id = title_s_match.group(1) if title_s_match else "1"

        clean_title = re.sub(r"^(S\d+\s*E\d+\s*:\s*|Ep\.?\s*\d+\s*:\s*)", "", title, flags=re.IGNORECASE)
        
        parsed_tracks.append({
            "title": clean_title,
            "url": mp3_url,
            "season": s_id
        })

    MAX_TRACKS = 50
    chunks = [parsed_tracks[i:i + MAX_TRACKS] for i in range(0, len(parsed_tracks), MAX_TRACKS)]
    
    for index, chunk in enumerate(chunks, start=1):
        filename = os.path.join(show_folder, f"volume_{index:02d}.xml")
        feed_title = f"{show_title_match.group(1)} - Volume {index}"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            f.write("<rss version=\"2.0\">\n")
            f.write("  <channel>\n")
            f.write(f"    <title>{html.escape(feed_title)}</title>\n")
            f.write("    <description>Yoto Audiobook Batch</description>\n")
            
            for track_num, track in enumerate(chunk, start=1):
                safe_url = html.escape(track["url"])
                safe_title = html.escape(track["title"])
                static_guid = f"{show_folder}-v{index}-t{track_num}"
                
                f.write("    <item>\n")
                f.write(f"      <title>{safe_title}</title>\n")
                # Cleaned direct URLs allow us to omit length metadata seamlessly
                f.write(f"      <enclosure url=\"{safe_url}\" type=\"audio/mpeg\" length=\"1000000\"/>\n")
                f.write(f"      <guid isPermaLink=\"false\">{static_guid}</guid>\n")
                f.write("    </item>\n")
                
            f.write("  </channel>\n")
            f.write("</rss>\n")
        print(f" -> Generated: {filename} ({len(chunk)} tracks)")

    print("[*] Initiating Automated GitHub Sync...")
    if not run_sys_command("git pull --rebase"):
        print("[-] Aborting sync: local tracking branch out of sync.")
        return
        
    run_sys_command(f"git add {show_folder}/")
    
    status = subprocess.run("git status --porcelain", shell=True, text=True, capture_output=True)
    if status.stdout.strip():
        run_sys_command(f'git commit -m "Automated tracking cleanup fix for {show_folder}"')
        if run_sys_command("git push"):
            print(f"[+] SUCCESS! Cleaned feeds updated online in your '{show_folder}' directory.")
        else:
            print("[-] Error: Git push routine failed.")
    else:
        print("[~] No updates detected. Cloud directory is already perfectly synchronized.")



if __name__ == "__main__":
    # Checks if you provided a link in the terminal command
    if len(sys.argv) > 1:
        TARGET_FEED = sys.argv[1]
    else:
        # Default fallback if you just type the command plain
        TARGET_FEED = "https://rss.art19.com/sixminutes"
        
    auto_sync_podcast(TARGET_FEED)
