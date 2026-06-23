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

def auto_sync_podcast(feed_url, force=False):
    print(f"[*] Fetching feed payload from: {feed_url}")
    
    try:
        # Upgraded to a modern, spoofed browser header to bypass Art19 security blockades
        req = urllib.request.Request(
            feed_url, 
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
        )
        with urllib.request.urlopen(req) as response:
            feed_data = response.read().decode("utf-8")
    except Exception as e:
        print(f"[-] Network connection error: {e}")
        sys.exit(1)

    # Robust multi-pattern extraction for the show title
    show_title_match = re.search(r"<title>(.*?)</title>", feed_data, re.DOTALL)
    if not show_title_match:
        # Fallback check if the main tag layout shifted
        show_title_match = re.search(r"<itunes:summary>(.*?)</itunes:summary>", feed_data, re.DOTALL)
        
    if not show_title_match:
        print("[-] Critical Error: Could not determine overall Show Title from feed.")
        sys.exit(1)
        
    raw_show_name = show_title_match.group(1).split("</title>")[0].strip()
    show_folder = sanitize_folder_name(raw_show_name)
    print(f"[+] Targeting path destination: ./{show_folder}/")
    os.makedirs(show_folder, exist_ok=True)

    items = feed_data.split("<item>")[1:]
    items.reverse()  # Chronological order
    print(f"[+] Extracted {len(items)} audio items total.")

    parsed_tracks = []
    for item in items:
        title_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        enclosure_match = re.search(r'<enclosure([^>]+)>', item)
        
        if not enclosure_match or not title_match:
            continue
            
        enclosure_attrs = enclosure_match.group(1)
        
        url_match = re.search(r'url="([^"]+)"', enclosure_attrs)
        if not url_match: 
            continue
        original_url = url_match.group(1)
        
        len_match = re.search(r'length="([^"]+)"', enclosure_attrs)
        original_length = len_match.group(1) if len_match else "0"
        
        title = title_match.group(1).strip()
        season_match = re.search(r'<itunes:season>(\d+)</itunes:season>', item)
        
        if season_match:
            s_id = season_match.group(1)
        else:
            title_s_match = re.search(r"\bS(\d+)\s*E\d+", title, re.IGNORECASE)
            s_id = title_s_match.group(1) if title_s_match else "1"

        clean_title = re.sub(r"^(S\d+\s*E\d+\s*:\s*|Ep\.?\s*\d+\s*:\s*)", "", title, flags=re.IGNORECASE)
        
        parsed_tracks.append({
            "title": clean_title,
            "url": original_url,
            "length": original_length,
            "season": s_id
        })

    MAX_TRACKS = 50
    chunks = [parsed_tracks[i:i + MAX_TRACKS] for i in range(0, len(parsed_tracks), MAX_TRACKS)]
    
    for index, chunk in enumerate(chunks, start=1):
        filename = os.path.join(show_folder, f"volume_{index:02d}.xml")
        feed_title = f"{raw_show_name} - Volume {index}"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            f.write("<rss version=\"2.0\" xmlns:itunes=\"http://itunes.com\">\n")
            f.write("  <channel>\n")
            f.write(f"    <title>{html.escape(feed_title)}</title>\n")
            f.write("    <description>Yoto Audiobook Batch</description>\n")
            
            for track_num, track in enumerate(chunk, start=1):
                # Preserves base64 equal signs (=) completely, only safe-escaping standard ampersands
                safe_url = track["url"].replace("&", "&amp;")
                safe_title = html.escape(track["title"])
                safe_length = track["length"]
                static_guid = f"{show_folder}-v{index}-t{track_num}"
                
                f.write("    <item>\n")
                f.write(f"      <title>{safe_title}</title>\n")
                f.write(f"      <enclosure url=\"{safe_url}\" type=\"audio/mpeg\" length=\"{safe_length}\"/>\n")
                f.write(f"      <guid isPermaLink=\"false\">{static_guid}</guid>\n")
                f.write("    </item>\n")
                
            f.write("  </channel>\n")
            f.write("</rss>\n")
        print(f" -> Generated: {filename} ({len(chunk)} tracks)")

    print("[*] Initiating Automated GitHub Sync...")
    # Stage the new XML variations first so Git understands they are part of the local workspace
    run_sys_command(f"git add {show_folder}/")

    # Now we can cleanly pull down any upstream changes without conflict
    if not run_sys_command("git pull --rebase"):
        print("[-] Aborting sync: local tracking branch out of sync.")
        return

    
    status = subprocess.run("git status --porcelain", shell=True, text=True, capture_output=True)
    if status.stdout.strip() or force:
        print("[*] Changes detected or --force applied. Committing...")
        commit_flag = " --allow-empty" if force else ""
        run_sys_command(f'git commit{commit_flag} -m "Forced rebuild and raw tracking parameter sync for {show_folder}"')
        if run_sys_command("git push"):
            print(f"[+] SUCCESS! Feeds updated online in your '{show_folder}' directory.")
        else:
            print("[-] Error: Git push routine failed.")
    else:
        print("[~] No updates detected. Use --force or -f to override and rebuild.")

if __name__ == "__main__":
    FORCE_UPDATE = "--force" in sys.argv or "-f" in sys.argv
    remaining_args = [arg for arg in sys.argv[1:] if arg not in ["--force", "-f"]]
    
    if remaining_args:
        TARGET_FEED = remaining_args[0]
    else:
        TARGET_FEED = "https://rss.art19.com/sixminutes"
        
    auto_sync_podcast(TARGET_FEED, force=FORCE_UPDATE)
