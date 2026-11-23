"""
extract some information from text from ESAF PDF
"""

import re
from glob import glob
from pathlib import Path

from markitdown import MarkItDown
from PyPDF2 import PdfReader
from .beamtimedb import BeamtimeDB

_KNOWN_USER_TYPES = (
    'On-site', 'Remote', 'Mail-in', 'Off-site/Co-proposer', 'Observer', 'Beamline Staff',
)


_TYPE_PATTERNS = [
    (re.compile(r'^On-site\b', re.I), 'On-site'),
    (re.compile(r'^Remote\b', re.I), 'Remote'),
    (re.compile(r'^Mail-in\b', re.I), 'Mail-in'),
    (re.compile(r'^Off-site', re.I), 'Off-site/Co-proposer'),
    (re.compile(r'^Observer\b', re.I), 'Observer'),
    (re.compile(r'^Beamline\s+Staff\b', re.I), 'Beamline Staff'),
    (re.compile(r'^Beamli\b', re.I), 'Beamline Staff'),  # PDF wraps "Beamline Staff" across two lines
]

_STOP_RE = re.compile(r'^(Beamline Comments|APS Experiment Review Board)', re.I)


def _parse_personnel_types(text):
    """Parse the Experiment Personnel table. Returns {(first_lower, last_lower): user_type}.

    The PDF renders the table as plain text. 'Beamline Staff' wraps across two lines:
    the person's data is on the 'Beamli ...' line; 'ne Staff' appears alone on the next.
    """
    result = {}
    idx = text.lower().find('experiment personnel and training')
    if idx < 0:
        return result
    for line in text[idx:].split('\n'):
        stripped = line.strip()
        if _STOP_RE.match(stripped):
            break
        for pattern, ut in _TYPE_PATTERNS:
            m = pattern.match(stripped)
            if m:
                parts = stripped[m.end():].split()
                if len(parts) >= 2:
                    result[(parts[0].lower(), parts[1].lower())] = ut
                break
    return result


def _parse_poc_name(line):
    """Extracts the Point of Contact line."""
    m = re.match(r'^([A-Z][A-Z\s]+),\s+([A-Z][A-Z\s]*?)(?=\s+[A-Z][A-Z\s]+,|\s+\d{2}-[A-Z]|$)', line.strip())
    if m:
        return m.group(1).strip().title(), m.group(2).strip().title()
    return None, None


def read_esaf_header(fname):
    md = MarkItDown()
    result = md.convert(fname)
    data =  {'printed_date': None,
             'beamline': None,
             'pen_line': None,
             'pen_key': None,
             'experiment_id': 0,
             'proposal_id': 0,
             'start_datetime': None,
             'end_datetime': None,
             'spokesperson': None,
             'beamline_contact_last': None,
             'beamline_contact_first': None,
             'experiment_type': None,
             'personnel': {}}

    data['personnel'] = _parse_personnel_types(result.text_content)
    capture_poc = False
    for line in result.text_content.split('\n'):
        if capture_poc:
            if not line.strip():
                continue
            if re.match(r'^[A-Z][A-Z\s]+,\s+[A-Z]', line):
                last, first = _parse_poc_name(line)
                if last:
                    data['beamline_contact_last'] = last
                    data['beamline_contact_first'] = first
                capture_poc = False
        elif line.startswith('Printed date:'):
            data['printed_date'] = line.replace('Printed date:', '').strip()
        elif line.startswith('ID Start Date:'):
            data['start_datetime'] = line.replace('ID Start Date:', '').strip()
        elif line.startswith('ID End Date:'):
            data['end_datetime'] = line.replace('ID End Date:', '').strip()
        elif line.startswith('BM Start Date:'):
            data['start_datetime'] = line.replace('BM Start Date:', '').strip()
        elif line.startswith('BM End Date:'):
            data['end_datetime'] = line.replace('BM End Date:', '').strip()
        elif line.startswith('Spokesperson:'):
            data['spokesperson'] = line.replace('Spokesperson:', '').strip()
        elif line.startswith('GUP ID:'):
            data['proposal_id'] = line.replace('GUP ID:', '').strip()
        elif line.startswith('Experiment ID:'):
            words = line.replace('Experiment ID:', '').strip().split()
            data['experiment_id'] = words[0]
            data['experiment_type'] = words[1].replace('(', '').replace(')', '')
        elif line.startswith('ESAF ID:'):
            words = line.replace('ESAF ID:', '').strip().split()
            data['experiment_id'] = words[0]
            data['experiment_type'] = words[1].replace('(', '').replace(')', '')
        elif line.startswith('PEN:'):
            data['pen_key'] = line.replace('PEN:', '').strip()
            data['pen_line'] = line
            words = data['pen_key'].split('-')
            data['beamline'] = '-'.join(words[:2])
        elif line.startswith('Point of Contact'):
            capture_poc = True
    return data

# from pypdf import PdfReader
def read_esaf_header_pdfreader(filename):
    """return dictionary of data from the top of the 
    first page of an ESAF PDF
    """
    print(f" READ PDF HEADER {filename=}")
    pdf_reader = PdfReader(open(filename, mode='rb'))
    page1_text = pdf_reader.pages[0].extract_text()
   
    data =  {'printed_date': None,
             'beamline': None,
             'pen_line': None,
             'pen_key': None,
             'experiment_id': '0',
             'proposal_id': '0',
             'start_datetime': None,
             'end_datetime': None,
             'spokesperson': None,
             'experiment_type': None}
    
    for line in page1_text.split('\n'):
        if line.startswith('Printed date:'):
            words = line.split(':')
            data['printed_date'] = words[1].strip()
        elif line.startswith('PEN:'):
            data['pen_line'] = line
            if 'Experiment ID:' in line:
                words = [s.strip() for s in line[4:].split('Experiment ID:')]
                data['pen_key'] = words[0]
                bwords = words[0].split('-')
                data['beamline'] = '-'.join(bwords[:2])
                ewords = words[1].split()
                data['experiment_id'] = ewords[0].strip()
                data['experiment_type'] = ewords[1].strip().replace('(','').replace(')','')
        elif line.startswith('ID Start Date:'):
            xline = line.replace('ID Start Date:', '')
            words = xline.split('ID End Date:')
            data['start_datetime'] = words[0].strip()
            data['end_datetime'] = words[1].strip()
        elif line.startswith('BM Start Date:'):
            xline = line.replace('BM Start Date:', '')
            words = xline.split('BM End Date:')
            data['start_datetime'] = words[0].strip()
            data['end_datetime'] = words[1].strip()

        elif line.startswith('Spokesperson:'):
            xline = line.replace('Spokesperson:', '')
            words = xline.split('GUP ID:')
            data['spokesperson'] = words[0].strip()
            data['proposal_id'] = words[1].strip()
    return data


BLNAMES = None

def get_beamline_names():
    """ lookup beamline names"""
    global BLNAMES
    beamdb = BeamtimeDB()
    BLNAMES = {}
    for row in beamdb.get_rows('apsbss_beamline'):
        if row.name is not None:
            name = row.name.lower().replace('-', '').replace(',', '')
            BLNAMES[name] = row.id
    return beamdb

def match_beamline(blname):
    """ match a beamline name, returning database ID for that beamline"""
    global BLNAMES
    if BLNAMES is None:
        get_beamline_names()
        
    name = blname.lower().replace('-', '').replace(',', '')
    bid = BLNAMES.get(name, None)
    if name == '13idd' or name == '13idc':
        bid = BLNAMES.get('13idcd', None)        
    if bid is None: 
        for key, xbid in BLNAMES.items():
            if key.startswith(name):
                bid = xbid
    if bid is None:
        bid = BLNAMES.get('unknown', None)
    return bid

def read_esaf_pdfs(run=None):
    beamdb = get_beamline_names()
    esaf_folder = beamdb.get_info('esaf_pdf_folder')
    print(f"ESAF FOLDER {esaf_folder=}")
    if run is None:
        run_id = beamdb.get_info('current_run_id')
        run_name = beamdb.get_rows('run', where={'id': int(run_id)},
                                   limit_one=True, none_if_empty=True)
        run_name = run_name.name
    else:
        run_name = run
        run = beamdb.get_rows('run', where={'name': run},
                                   limit_one=True, none_if_empty=True)
        run_id = run.id
        
    for bname in ('BMC', 'BMD',  'ID CD', 'IDE'):
        folder = Path(esaf_folder, run_name, bname)
        for pdffile in glob(folder.as_posix() + '/*'):
            if not pdffile.endswith('.pdf'):
                continue                
            data = read_esaf_header(pdffile)
            print("READ PDF ", pdffile)
            if data['beamline'] is None:
                continue
            bl_id = match_beamline(data['beamline'])
            if data['proposal_id'] in (None, ''):
                data['proposal_id'] = 0
            try:
                proprow = beamdb.get_row('proposal', where={'id': int(data['proposal_id'])})
            except ValueError:
                proprow = None
                data['proposal_id'] = 0                
            if data['beamline_contact_last']:
                try:
                    contacts = beamdb.get_users(
                        last_name=data['beamline_contact_last'],
                        first_name=data['beamline_contact_first'],
                    )
                    if contacts is None:
                        contacts = beamdb.get_users(last_name=data['beamline_contact_last'])
                    if contacts:
                        beamdb.update('experiment', where={'id': int(data['experiment_id'])},
                                      beamline_contact_id=contacts[0].id)
                        print(f"  set beamline_contact={data['beamline_contact_last']} on experiment {data['experiment_id']}")
                except Exception as exc:
                    print(f"  could not set beamline_contact on experiment {data['experiment_id']}: {exc}")
            if proprow is not None:
                try:
                    beamdb.update('experiment', where={'id': int(data['experiment_id'])},
                                  proposal_id=int(data['proposal_id']),
                                  beamline_id=bl_id, run_id=run_id)
                except Exception:
                    print("could not update experiment from PDF")

            if data['personnel']:
                type_rows = {row.name: row.id for row in beamdb.get_rows('user_type')}

                # Use filename as fallback
                esaf_id = int(data['experiment_id'])
                if esaf_id == 0:
                    m = re.search(r'ESAF-(\d+)', Path(pdffile).name)
                    if m:
                        esaf_id = int(m.group(1))

                if esaf_id == 0:
                    print(f"  skipping personnel: could not determine experiment ID")
                else:
                    try:
                        ep_rows = beamdb.get_rows('experiment_person',
                                                 where={'experiment_id': esaf_id})
                        for ep in ep_rows:
                            person = beamdb.get_user(id=ep.person_id)
                            if person is None:
                                continue
                            key = (person.first_name.lower(), person.last_name.lower())
                            user_type = data['personnel'].get(key)
                            if user_type and user_type in type_rows:
                                beamdb.update('experiment_person',
                                              where={'experiment_id': esaf_id,
                                                     'person_id': ep.person_id},
                                              user_type_id=type_rows[user_type])
                                print(f"  user_type={user_type} -> {person.first_name} {person.last_name}")
                    except Exception as exc:
                        print(f"  could not set user_type on experiment {esaf_id}: {exc}")

                if esaf_id != 0:
                    try:
                        staff_type_id = type_rows.get('Beamline Staff')
                        for (first, last), user_type in data['personnel'].items():
                            if user_type != 'Beamline Staff':
                                continue
                            persons = beamdb.get_users(last_name=last.title(), first_name=first.title())
                            if not persons:
                                persons = beamdb.get_users(last_name=last.title())
                            if not persons:
                                print(f"  staff not found in DB: {first} {last}")
                                continue
                            person = persons[0]
                            existing = beamdb.get_row('experiment_person', where={
                                'experiment_id': esaf_id,
                                'person_id': person.id,
                            })
                            if existing is None:
                                beamdb.add_row('experiment_person',
                                               experiment_id=esaf_id,
                                               person_id=person.id,
                                               user_type_id=staff_type_id)
                                print(f"  added {person.first_name} {person.last_name} as Beamline Staff")
                    except Exception as exc:
                        print(f"  could not add staff to experiment_person for experiment {esaf_id}: {exc}")



def read_pending_pdfs(run=None):
    beamdb = get_beamline_names()
    esaf_folder = '/home/detector/Pending_ESAFS'
    print(f"ESAF FOLDER {esaf_folder=}")
    if run is None:
        run_id = beamdb.get_info('current_run_id')
        run_name = beamdb.get_rows('run', where={'id': int(run_id)},
                                   limit_one=True, none_if_empty=True)
        run_name = run_name.name
    else:
        run_name = run
        run = beamdb.get_rows('run', where={'name': run},
                                   limit_one=True, none_if_empty=True)
        run_id = run.id
        
    for pdffile in glob(esaf_folder + '/*'):
        if not pdffile.endswith('.pdf'):
            continue
        print(pdffile)
        data = read_esaf_header(pdffile)
        if data['proposal_id'] in (None, ''):
            data['proposal_id'] = 0

        exptrow = beamdb.get_experiment(int(data['experiment_id']))
        if exptrow is not None and exptrow.proposal_id is None:
            bl_id = match_beamline(data['beamline'])
            proprow = beamdb.get_row('proposal', where={'id': int(data['proposal_id'])})
            try:
                proprow = beamdb.get_row('proposal', where={'id': int(data['proposal_id'])})
            except ValueError:
                proprow = None
                data['proposal_id'] = 0                
            if proprow is not None:
                beamdb.update('experiment', where={'id': int(data['experiment_id'])},
                              proposal_id=int(data['proposal_id']), beamline_id=bl_id,
                              run_id=run_id)

              
                
