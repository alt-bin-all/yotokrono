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

def auto_sync_podcast(feed_url):
    print(f"[*] Fetching feed payload from: {feed_url}")
    
    # 1. Download Feed
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            feed_data = response.read().decode("utf-8")
    except Exception as e:
        print(f"[-] Network connection error: {e}")
        sys.exit(1)

    # 2. Extract Show Identity for Git Folder Pathing
    show_title_match = re.search(r"<title>(.*?)</title>", feed_data, re.DOTALL)
    if not show_title_match:
        print("[-] Critical Error: Could not determine overall Show Title from feed.")
        sys.exit(1)
        
    show_folder = sanitize_folder_name(show_title_match.group(1))
    print(f"[+] Targeting path destination: ./{show_folder}/")
    
    # Ensure directory framework exists
    os.makedirs(show_folder, exist_ok=True)

    # 3. Parse Item Substructures & Sort Chronologically
    items = feed_data.split("<item>")[1:]
    items.reverse()  # Guarantees old episodes come first (Ep 1, Ep 2...)
    print(f"[+] Extracted {len(items)} audio items total.")

    parsed_tracks = []
    for item in items:
        title_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        url_match = re.search(r'<enclosure[^>]*url="([^"]+)"', item)
        season_match = re.search(r'<itunes:season>(\d+)</itunes:season>', item)
        
        if not url_match or not title_match:
            continue
            
        title = title_match.group(1).strip()
        mp3_url = url_match.group(1).strip()
        
        # Pull explicit season if it exists, otherwise fall back to title sniffing
        if season_match:
            s_id = season_match.group(1)
        else:
            title_s_match = re.search(r"\bS(\d+)\s*E\d+", title, re.IGNORECASE)
            s_id = title_s_match.group(1) if title_s_match else "1"

        # Strip long repeating namespace codes to keep text moving cleanly on small app players
        clean_title = re.sub(r"^(S\d+\s*E\d+\s*:\s*|Ep\.?\s*\d+\s*:\s*)", "", title, flags=re.IGNORECASE)
        
        parsed_tracks.append({
            "title": clean_title,
            "url": mp3_url,
            "season": s_id
        })

    # 4. Process Multi-Episode Chronological Splits (Batches of 50)
    MAX_TRACKS = 50
    chunks = [parsed_tracks[i:i + MAX_TRACKS] for i in range(0, len(parsed_tracks), MAX_TRACKS)]
    
    for index, chunk in enumerate(chunks, start=1):
        # Establish robust chronological name spacing 
        filename = os.path.join(show_folder, f"volume_{index:02d}.xml")
        feed_title = f"{show_title_match.group(1)} - Volume {index}"
        
        # Build out permanent audiobook XML spec
        with open(filename, "w", encoding="utf-8") as f:
            f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            f.write("<rss version=\"2.0\">\n")
            f.write("  <channel>\n")
            f.write(f"    <title>{html.escape(feed_title)}</title>\n")
            f.write(f"    <description>Yoto Audiobook Batch</description>\n")
            
            for track_num, track in enumerate(chunk, start=1):
                safe_url = html.escape(track["url"])
                safe_title = html.escape(track["title"])
                
                # Immutable UUID to trick Yoto cache out of auto-purging old audio histories
                static_guid = f"{show_folder}-v{index}-t{track_num}"
                
                f.write("    <item>\n")
                f.write(f"      <title>{safe_title}</title>\n")
                f.write(f"      <enclosure url=\"{safe_url}\" type=\"audio/mpeg\" length=\"0\"/>\n")
                f.write(f"      <guid isPermaLink=\"false\">{static_guid}</guid>\n")
                f.write("    </item>\n")
                
            f.write("  </channel>\n")
            f.write("</rss>\n")
        print(f" -> Generated: {filename} ({len(chunk)} tracks)")

    # 5. Native Git Lifecycle Pushing Execution
    print("[*] Initiating Automated GitHub Sync...")
    if not run_sys_command("git pull --rebase"):
        print("[-] Aborting sync: local tracking branch out of sync.")
        return
        
    run_sys_command(f"git add {show_folder}/")
    
    # Only commit if actual system adjustments exist
    status = subprocess.run("git status --porcelain", shell=True, text=True, capture_output=True)
    if status.stdout.strip():
        run_sys_command(f'git commit -m "Automated update for {show_folder} audiobook assets"')
        if run_sys_command("git push"):
            print(f"[+] SUCCESS! Feeds updated online in your '{show_folder}' directory.")
        else:
            print("[-] Error: Git push routine failed.")
    else:
        print("[~] No updates detected. Cloud directory is already perfectly synchronized.")

if __name__ == "__main__":
    # Pass ANY target podcast RSS URL right here to scale this system
    TARGET_FEED = "https://art19.com"
    auto_sync_podcast(TARGET_FEED)
