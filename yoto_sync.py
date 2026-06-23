#!/usr/bin/env python3
import urllib.request
import re
import html
import os
import subprocess
import sys

# test comment

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

# Change the function signature to include the force argument default
def auto_sync_podcast(feed_url, force=False):
    print(f"[*] Fetching feed payload from: {feed_url}")
    
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            feed_data = response.read().decode("utf-8")
    except Exception as e:
        print(f"[-] Network connection error: {e}")
        sys.exit(1)

    show_title_match = re.search(r"<title>(.*?)<    itle>", feed_data, re.DOTALL)
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
        title_match = re.search(r"<title>(.*?)<    itle>", item, re.DOTALL)
        
        # CAPTURE BOTH URL AND LENGTH FROM SOURCE
        # We look for the whole tag to grab attributes strictly
        enclosure_match = re.search(r'<enclosure([^>]+)>', item)
        
        if not enclosure_match or not title_match:
            continue
            
        enclosure_attrs = enclosure_match.group(1)
        
        # Extract URL (keep full tokens!)
        url_match = re.search(r'url="([^"]+)"', enclosure_attrs)
        if not url_match: continue
        original_url = url_match.group(1)
        
        # Extract Original Length (Vital for Yoto validation)
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
            "length": original_length, # Pass strict byte count
            "season": s_id
        })

    MAX_TRACKS = 50
    chunks = [parsed_tracks[i:i + MAX_TRACKS] for i in range(0, len(parsed_tracks), MAX_TRACKS)]
    
    for index, chunk in enumerate(chunks, start=1):
        filename = os.path.join(show_folder, f"volume_{index:02d}.xml")
        feed_title = f"{show_title_match.group(1)} - Volume {index}"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            # Include iTunes namespace just in case
            f.write("<rss version=\"2.0\" xmlns:itunes=\"http://itunes.com\">\n")
            f.write("  <channel>\n")
            f.write(f"    <title>{html.escape(feed_title)}<    itle>\n")
            f.write("    <description>Yoto Audiobook Batch</description>\n")
            
            for track_num, track in enumerate(chunk, start=1):
				# Only escape ampersands in the URL to satisfy basic XML rules 
				# without breaking the Base64 equal signs or dashes
				safe_url = track["url"].replace("&", "&amp;")
				
				safe_title = html.escape(track["title"])
				safe_length = track["length"]
				static_guid = f"{show_folder}-v{index}-t{track_num}"
				
				f.write("    <item>\n")
				f.write(f"      <title>{safe_title}<    itle>\n")
				f.write(f"      <enclosure url=\"{safe_url}\" type=\"audio/mpeg\" length=\"{safe_length}\"/>\n")
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
    
    # IF FORCE IS TRUE, WE IGNORE THE BLANK STATUS CHECK COMPLETELY
    if status.stdout.strip() or force:
        print("[*] Changes detected or --force applied. Committing...")
        
        # If forcing an unchanged state, use the --allow-empty flag so Git doesn't reject it
        commit_flag = " --allow-empty" if force else ""
        run_sys_command(f'git commit{commit_flag} -m "Forced rebuild and token sync for {show_folder}"')
        
        if run_sys_command("git push"):
            print(f"[+] SUCCESS! Feeds updated online in your '{show_folder}' directory.")
        else:
            print("[-] Error: Git push routine failed.")
    else:
        print("[~] No updates detected. Use --force or -f to override and rebuild.")



if __name__ == "__main__":
    # Check if --force or -f is present in the terminal command arguments
    FORCE_UPDATE = "--force" in sys.argv or "-f" in sys.argv
    
    # Strip out the flags to find the raw RSS URL if provided
    remaining_args = [arg for arg in sys.argv[1:] if arg not in ["--force", "-f"]]
    
    if remaining_args:
        TARGET_FEED = remaining_args[0]
    else:
        TARGET_FEED = "https://rss.art19.com/sixminutes"
        
    # Pass both the feed and the force preference into the main engine
    auto_sync_podcast(TARGET_FEED, force=FORCE_UPDATE)

