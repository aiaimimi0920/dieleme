import os
import shutil
import glob
import re
from datetime import datetime

DATAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datas')

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def move_files():
    print(f"Cleaning datas directory: {DATAS_DIR}")
    
    # 1. Archive JSONs (YYYY-MM-DD.json)
    archive_dir = os.path.join(DATAS_DIR, 'archive')
    ensure_dir(archive_dir)
    
    json_pattern = re.compile(r'^(\d{4})-\d{2}-\d{2}\.json$')
    
    count_json = 0
    for filename in os.listdir(DATAS_DIR):
        match = json_pattern.match(filename)
        if match:
            year = match.group(1)
            year_dir = os.path.join(archive_dir, year)
            ensure_dir(year_dir)
            
            src = os.path.join(DATAS_DIR, filename)
            dst = os.path.join(year_dir, filename)
            shutil.move(src, dst)
            count_json += 1
            if count_json % 100 == 0:
                print(f"Moved {count_json} JSONs...", end='\r')
    
    print(f"\nMoved {count_json} JSON files to archive.")

    # 2. HTML Files
    html_dir = os.path.join(DATAS_DIR, 'html')
    ensure_dir(html_dir)
    
    count_html = 0
    for filepath in glob.glob(os.path.join(DATAS_DIR, 'item-*.html')):
        filename = os.path.basename(filepath)
        dst = os.path.join(html_dir, filename)
        shutil.move(filepath, dst)
        count_html += 1
        if count_html % 100 == 0:
            print(f"Moved {count_html} HTMLs...", end='\r')
            
    print(f"\nMoved {count_html} HTML files.")

    # 3. Retry Files
    retry_dir = os.path.join(DATAS_DIR, 'retry')
    ensure_dir(retry_dir)
    
    count_retry = 0
    for filepath in glob.glob(os.path.join(DATAS_DIR, 'item-*.html.retry')):
        filename = os.path.basename(filepath)
        dst = os.path.join(retry_dir, filename)
        shutil.move(filepath, dst)
        count_retry += 1
    
    print(f"Moved {count_retry} Retry files.")

    # 4. Failed Files
    failed_dir = os.path.join(DATAS_DIR, 'failed')
    ensure_dir(failed_dir)
    
    count_failed = 0
    for filepath in glob.glob(os.path.join(DATAS_DIR, 'item-*.html.failed')):
        filename = os.path.basename(filepath)
        dst = os.path.join(failed_dir, filename)
        shutil.move(filepath, dst)
        count_failed += 1
        
    print(f"Moved {count_failed} Failed files.")
    
    # Check what's left
    print("\nRemaining files in root:")
    for f in os.listdir(DATAS_DIR):
        if os.path.isfile(os.path.join(DATAS_DIR, f)):
            print(f" - {f}")

if __name__ == '__main__':
    move_files()
