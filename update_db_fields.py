from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import time
import utils


def _process_row(row):
    nid = row['id']
    path = row['path']
    p = Path(path)
    size = 0
    chars = 0
    start = time.time()
    if p.exists() and p.is_file():
        try:
            text = utils.read_text_with_encoding(p)
            chars = len(text)
            size = p.stat().st_size
            try:
                utils.memdb_set(str(p.resolve()), text, p.stat().st_mtime)
            except Exception:
                pass
        except Exception:
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            chars = 0
    duration = time.time() - start
    return nid, size, chars, duration


def main(thread_workers: int = 8, batch_commit: int = 100, wait_timeout: float = 2.0):
    conn = utils.get_db()
    cur = conn.execute('SELECT id, path FROM novels where size IS NULL OR chars IS NULL')
    rows = cur.fetchall()
    total = len(rows)
    print(f'Found {total} rows to update')

    batch_size = batch_commit or 100
    overall_updated = 0
    overall_processed = 0
    start_all = time.time()

    # Process in batches to limit memory and commit once per batch
    for bstart in range(0, total, batch_size):
        batch_rows = rows[bstart:bstart+batch_size]
        bcount = len(batch_rows)
        print(f'Processing batch {bstart//batch_size + 1}: {bcount} items')

        batch_results = []
        with ThreadPoolExecutor(max_workers=thread_workers) as ex:
            futures = {ex.submit(_process_row, row): row for row in batch_rows}
            futures_set = set(futures.keys())
            processed = 0
            while futures_set:
                done, not_done = wait(futures_set, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                if not done:
                    elapsed = time.time() - start_all
                    in_flight = len(futures_set)
                    print(f'Batch progress {overall_processed}/{total} — In-flight: {in_flight} — Elapsed: {elapsed:.1f}s')
                    continue
                for fut in done:
                    futures_set.discard(fut)
                    row = futures.get(fut)
                    try:
                        nid, size, chars, duration = fut.result()
                        batch_results.append((nid, size, chars))
                        processed += 1
                        overall_processed += 1
                        print(f'[{overall_processed}/{total}] id={nid} size={size} chars={chars} time={duration:.2f}s')
                    except Exception as e:
                        print(f'Error processing row {row["id"] if row else "?"}: {e}')

        # Single commit for the batch
        for nid, size, chars in batch_results:
            try:
                conn.execute('UPDATE novels SET size = ?, chars = ? WHERE id = ?', (size, chars, nid))
                overall_updated += 1
            except Exception as e:
                print(f'DB update failed for id={nid}: {e}')
        conn.commit()
        print(f'Batch committed: {len(batch_results)} rows updated. Total updated: {overall_updated}')

    conn.close()
    print(f'Done. Updated {overall_updated} / {total} rows. Elapsed: {time.time()-start_all:.1f}s')


if __name__ == '__main__':
    main()
