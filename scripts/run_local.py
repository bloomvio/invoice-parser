"""§17 — Process one local folder without the API/queue layer.

Usage:
    python scripts/run_local.py <path/to/invoices/> [--format xlsx|json|both]

Output files are written to the same directory as the input.
"""

import asyncio
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()


async def run(folder: str, output_format: str) -> None:
    from invoice_parser.config import settings
    from invoice_parser.storage.local import LocalStorage
    from invoice_parser.worker.emit import generate_json, generate_xlsx
    from invoice_parser.worker.ingest import LocalPathSource
    from invoice_parser.worker.pipeline import process_invoice_segment
    from invoice_parser.worker.render import render_pages
    from invoice_parser.worker.segment import segment_pdf

    storage = LocalStorage(folder)
    source = LocalPathSource(folder, recursive=False)
    file_refs = await source.list_pdfs()

    if not file_refs:
        print(f"No PDFs found in {folder}")
        return

    print(f"Found {len(file_refs)} PDF(s). Processing...")

    job_id = "local_" + secrets.token_hex(4)
    all_results = []
    all_skipped = []

    for file_ref in file_refs:
        print(f"  -> {file_ref.filename}")
        pdf_bytes = await source.fetch(file_ref)

        pages = await asyncio.to_thread(render_pages, pdf_bytes)
        for p in pages:
            await storage.put(
                f"jobs/{job_id}/renders/{file_ref.file_id}/page_{p.page_number}_hires.png",
                p.hi_res, "image/png",
            )
            await storage.put(
                f"jobs/{job_id}/renders/{file_ref.file_id}/page_{p.page_number}_thumb.png",
                p.lo_res, "image/png",
            )

        seg = await segment_pdf([p.lo_res for p in pages])
        all_skipped.extend(seg.skipped_pages)

        for idx, inv_seg in enumerate(seg.invoices, start=1):
            result = await process_invoice_segment(
                storage=storage,
                job_id=job_id,
                file_id=file_ref.file_id,
                pages=inv_seg.pages,
                invoice_index=idx,
            )
            inv_id = "inv_" + secrets.token_hex(4)
            all_results.append((inv_id, result))
            inv = result.invoice
            print(f"     invoice {idx}: status={inv.status} vendor={inv.vendor_name!r} "
                  f"total={inv.total} number={inv.invoice_number!r}")

    # Write outputs
    if output_format in ("xlsx", "both"):
        out_path = os.path.join(folder, f"invoices_{job_id}.xlsx")
        with open(out_path, "wb") as fh:
            fh.write(generate_xlsx(job_id, all_results, all_skipped))
        print(f"\nXLSX written to {out_path}")

    if output_format in ("json", "both"):
        out_path = os.path.join(folder, f"invoices_{job_id}.json")
        with open(out_path, "wb") as fh:
            fh.write(generate_json(job_id, all_results, all_skipped))
        print(f"JSON written to {out_path}")

    total_cost = sum(r.cost_usd for _, r in all_results)
    print(f"\nDone. {len(all_results)} invoice(s) extracted. "
          f"Estimated cost: ${total_cost:.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_local.py <folder> [xlsx|json|both]")
        sys.exit(1)

    folder = sys.argv[1]
    fmt = sys.argv[2] if len(sys.argv) > 2 else "xlsx"
    asyncio.run(run(folder, fmt))
