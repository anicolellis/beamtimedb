"""
Extract ETR data from an APS proposal PDF and match to experiments in the DB.
"""

import re
from glob import glob
from pathlib import Path
from markitdown import MarkItDown
from PyPDF2 import PdfReader

from .esafpdf import get_beamline_names, match_beamline


_BEAMLINE_PATTERNS = [
    r'13-ID-\s*C,D',
    r'13-ID-E',
    r'13-BM-C',
    r'13-BM-D',
    r'6-BM-A,B',
    r'3-ID-B,C,D',
]
_BEAMLINE_RE = re.compile('|'.join(_BEAMLINE_PATTERNS))


def _normalise_beamline(raw):
    """Removes spaces in beamline names."""
    return re.sub(r'\s+', '', raw)


def _parse_section_headers(text):
    """Returns ETR from section headers in later pages."""
    pattern = re.compile(
        r'(\d{6,})\s*:\s*APS:\s*(\d{4}-\d+)\s*:\s*(.+?)\s+-\s+APS Experiment Time Request',
        re.IGNORECASE,
    )
    seen, results = set(), []
    for m in pattern.finditer(text):
        etr_number = int(m.group(1))
        run_cycle = m.group(2).strip()
        beamline = _normalise_beamline(m.group(3).strip())
        key = (etr_number, run_cycle, beamline)
        if key not in seen:
            seen.add(key)
            results.append({'etr_number': etr_number, 'run_cycle': run_cycle, 'beamline': beamline})
    return results


def _parse_etr_table(fname):
    """Extracts ETR rows from the PDF using PyPDF2 raw text."""
    reader = PdfReader(open(fname, 'rb'))
    seen, results = set(), []
    for page in reader.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            m = re.match(r'^\s*(\d{6,})\s+APS:\s*(\d{4}-\d+)\s+(.*)', line)
            if not m:
                continue
            etr_number = int(m.group(1))
            run_cycle = m.group(2).strip()
            rest = m.group(3)
            for bl_match in _BEAMLINE_RE.finditer(rest):
                beamline = _normalise_beamline(bl_match.group())
                key = (etr_number, run_cycle, beamline)
                if key not in seen:
                    seen.add(key)
                    results.append({'etr_number': etr_number, 'run_cycle': run_cycle, 'beamline': beamline})
    return results


def read_proposal_pdf(fname):
    """Parses a proposal PDF and returns proposal_id and ETR number."""
    md = MarkItDown()
    text = md.convert(fname).text_content

    data = {'proposal_id': None, 'etrs': []}

    for line in text.split('\n'):
        m = re.match(r'^Proposal\s+(\d{6,})', line.strip())
        if m:
            data['proposal_id'] = int(m.group(1))
            break

    etrs = _parse_etr_table(fname)
    if not etrs:
        etrs = _parse_section_headers(text)
    data['etrs'] = etrs
    return data


def _apply_etrs(beamdb, fname, run_map):
    """Parses one proposal PDF and updates the etr_number on matching experiments."""
    data = read_proposal_pdf(fname)
    proposal_id = data['proposal_id']
    if proposal_id is None:
        print(f"  Could not extract proposal ID from {fname}")
        return

    print(f"Proposal {proposal_id}: {len(data['etrs'])} ETR found")

    for etr in data['etrs']:
        run_cycle = etr['run_cycle']
        beamline = etr['beamline']
        etr_number = etr['etr_number']

        run_id = run_map.get(run_cycle)
        if run_id is None:
            print(f"  ETR {etr_number}: run '{run_cycle}' not found in DB")
            continue

        bl_id = match_beamline(beamline)
        if bl_id is None:
            print(f"  ETR {etr_number}: beamline '{beamline}' not found in DB")
            continue

        expt = beamdb.get_row('experiment', where={
            'run_id': run_id,
            'beamline_id': bl_id,
            'proposal_id': proposal_id,
        })
        if expt is None:
            print(f"  ETR {etr_number}: no experiment for "
                  f"run={run_cycle} beamline={beamline} proposal={proposal_id}")
            continue

        print(f"  ETR {etr_number} -> experiment {expt.id} "
              f"(run={run_cycle}, beamline={beamline})")
        beamdb.update('experiment', where={'id': expt.id}, etr_number=etr_number)


def match_etrs_to_experiments(fname):
    """Parses a single proposal PDF and set etr_number on matching experiments."""
    beamdb = get_beamline_names()
    run_map = {row.name: row.id for row in beamdb.get_rows('run')}
    _apply_etrs(beamdb, fname, run_map)


def read_proposal_pdfs(run=None):
    """Processes all proposal PDFs."""
    beamdb = get_beamline_names()
    proposal_folder = beamdb.get_info('proposal_pdf_folder')
    if not proposal_folder:
        print("'proposal_pdf_folder' not set in info table")
        return

    if run is None:
        run_id = beamdb.get_info('current_run_id')
        run_row = beamdb.get_rows('run', where={'id': int(run_id)},
                                  limit_one=True, none_if_empty=True)
        run_name = run_row.name
    else:
        run_name = run
        run_id = beamdb.get_rows('run', where={'name': run},
                                 limit_one=True, none_if_empty=True).id

    year = run_name.split('-')[0]
    folder = Path(proposal_folder, year, run_name)
    print(f"Proposal PDF folder: {folder}")
    run_map = {row.name: row.id for row in beamdb.get_rows('run')}

    pdfs = glob(str(folder / "*.pdf")) + glob(str(folder / "*.PDF"))
    if not pdfs:
        print("No PDF files found")
        return

    for pdffile in sorted(pdfs):
        print(f"\nProcessing {pdffile}")
        _apply_etrs(beamdb, pdffile, run_map)
