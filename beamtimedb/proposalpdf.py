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

_KNOWN_SOURCES = (
    'National Science Foundation (NSF)',
    'DOE, Office of Basic Energy Sciences (BES)',
    'DOE, Other (includes LDRD)',
    'National Aeronautics and Space Administration (NASA)',
    'National Nuclear Security Administration (NNSA)',
    'Other U.S. Government',
    'U.S. Department of Defense (DOD)',
    'Foreign',
    'Other',
)


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


def _parse_funding_line(line):
    """Parse one funding source line. Returns dict or None."""
    line = line.strip()
    if not line:
        return None

    # Markdown table row
    if line.startswith('|') and line.endswith('|'):
        cells = [c.strip() for c in line.split('|')[1:-1]]
        meaningful = [c for c in cells if c]
        if len(meaningful) < 2:
            return None
        try:
            pct = int(meaningful[-1])
        except ValueError:
            return None
        if not (1 <= pct <= 100):
            return None
        source = meaningful[0]
        grant = meaningful[-2] if len(meaningful) >= 3 else ''
        details = ' '.join(meaningful[1:-2]) if len(meaningful) >= 4 else ''
        return {'source': source, 'details': details, 'grant_number': grant, 'percentage': pct}

    # Match known source category from the start of the line
    source = None
    rest = line
    for known in _KNOWN_SOURCES:
        if line.lower().startswith(known.lower()):
            source = known
            rest = line[len(known):].strip()
            break

    # source ends with ) for unlisted agencies
    if source is None:
        m = re.match(r'^(.+\))\s+(.*)', line)
        if m:
            source = m.group(1).strip()
            rest = m.group(2).strip()
        else:
            return None

    tokens = rest.split()
    if not tokens:
        return None
    try:
        pct = int(tokens[-1])
    except ValueError:
        return None
    if not (1 <= pct <= 100):
        return None

    remaining = tokens[:-1]
    if not remaining:
        return {'source': source, 'details': '', 'grant_number': '', 'percentage': pct}

    if re.search(r'\d', remaining[-1]):
        grant_number = remaining[-1]
        details_tokens = remaining[:-1]
        if details_tokens and not re.match(r'^[a-zA-Z0-9]', grant_number):
            grant_number = details_tokens[-1] + grant_number
            details_tokens = details_tokens[:-1]
        return {'source': source, 'details': ' '.join(details_tokens),
                'grant_number': grant_number, 'percentage': pct}
    return {'source': source, 'details': ' '.join(remaining),
            'grant_number': '', 'percentage': pct}


def _parse_funding_sources(text):
    """Extract funding sources from MarkItDown text. Returns list of dicts."""
    _HEADER_KW = {'source', 'details', 'grant', 'percentage', 'agency', 'division'}

    in_funding = False
    funding_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if re.search(r'funding\s+sources?', stripped, re.IGNORECASE):
            in_funding = True
            continue
        if not in_funding:
            continue
        if re.match(r'^#+\s+', stripped):
            break
        if re.search(r'experiment\s+time\s+request', stripped, re.IGNORECASE):
            break
        funding_lines.append(stripped)

    results = []
    for line in funding_lines:
        if not line:
            if results:
                break
            continue
        if re.search(r'\bPage \d+ of \d+\b', line):
            continue
        if re.match(r'^Pre-Decisional', line, re.IGNORECASE):
            continue
        if re.match(r'^[\|\s\-:]+$', line):
            continue
        words = set(re.split(r'[\s|]+', line.lower()))
        if words & _HEADER_KW and not any(c.isdigit() for c in line):
            continue
        entry = _parse_funding_line(line)
        if entry:
            results.append(entry)
        elif results:
            break
    return results


def read_proposal_pdf(fname):
    """Parses a proposal PDF and returns proposal_id, ETRs, and funding sources."""
    md = MarkItDown()
    text = md.convert(fname).text_content

    data = {'proposal_id': None, 'etrs': [], 'funding': []}

    for line in text.split('\n'):
        m = re.match(r'^Proposal\s+(\d{6,})', line.strip())
        if m:
            data['proposal_id'] = int(m.group(1))
            break

    etrs = _parse_etr_table(fname)
    if not etrs:
        etrs = _parse_section_headers(text)
    data['etrs'] = etrs
    data['funding'] = _parse_funding_sources(text)
    return data


def _apply_funding(beamdb, proposal_id, funding_sources):
    """Stores funding sources and links them to a proposal."""
    if beamdb.get_row('proposal', where={'id': proposal_id}) is None:
        print(f"  Skipping funding: proposal {proposal_id} not in DB")
        return
    for fs in funding_sources:
        existing = beamdb.get_row('funding', where={
            'source': fs['source'], 'grant_number': fs['grant_number'],
        })
        if existing:
            fund_id = existing.id
        else:
            beamdb.add_row('funding', source=fs['source'], details=fs['details'],
                           grant_number=fs['grant_number'], percentage=fs['percentage'])
            fund_row = beamdb.get_row('funding', where={
                'source': fs['source'], 'grant_number': fs['grant_number'],
            })
            fund_id = fund_row.id

        link = beamdb.get_row('proposal_funding', where={
            'proposal_id': proposal_id, 'funding_id': fund_id,
        })
        if not link:
            beamdb.add_row('proposal_funding', proposal_id=proposal_id, funding_id=fund_id)
            print(f"  Funding: {fs['source']} / {fs['grant_number']} ({fs['percentage']}%)")


def _apply_etrs(beamdb, fname, run_map):
    """Parses one proposal PDF and updates the etr_number on matching experiments."""
    data = read_proposal_pdf(fname)
    proposal_id = data['proposal_id']
    if proposal_id is None:
        print(f"  Could not extract proposal ID from {fname}")
        return

    print(f"Proposal {proposal_id}: {len(data['etrs'])} ETR found")

    if beamdb.get_row('proposal', where={'id': proposal_id}) is not None:
        beamdb.update('proposal', where={'id': proposal_id}, pdf_file=fname)

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

    if data['funding']:
        print(f"  {len(data['funding'])} funding source(s) found")
        _apply_funding(beamdb, proposal_id, data['funding'])
    else:
        print(f"  No funding sources found")


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
