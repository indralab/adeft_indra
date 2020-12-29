import json
import zlib
import sqlite3
import lxml.etree as etree
from contextlib import closing
from collections import Counter
from multiprocessing import Pool
from indra.literature.adeft_tools import universal_extract_text, \
    filter_paragraphs


from adeft_indra.locations import CONTENT_DB_PATH, UPDATE_DB_PATH


def _extract_text(arg):
    return universal_extract_text(arg[0], contains=arg[1])


def universal_extract_texts(xmls, contains=None, n_jobs=1):
    if n_jobs > 1:
        with Pool(n_jobs) as pool:
            result = pool.map(_extract_text,
                              [(xml, contains) for xml in xmls])
        return result
    else:
        return [universal_extract_text(xml, contains=contains) for xml in xmls]


def get_plaintexts_for_pmids(pmids, contains=None, n_jobs=1):
    pmids = tuple(pmids)
    query = \
        f"""SELECT
                pmid, paragraphs
            FROM
                text_content
            WHERE
                pmid IN ({','.join(['?']*len(pmids))})
    """
    with closing(sqlite3.connect(UPDATE_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            paragraphs_list = cur.execute(query, pmids).fetchall()
    if contains is None:
        contains = []
    paragraphs_list = ((pmid, filter_paragraphs(json.loads(paragraphs),
                                                contains=contains))
                       for pmid, paragraphs in paragraphs_list)
    return {pmid: plaintext for pmid, plaintext in paragraphs_list
            if len(plaintext) > 1}


def get_pmids_for_agent_text(agent_text):
    query = \
        """SELECT
                pmid
            FROM
                agent_text_pmids
            WHERE agent_text = ?;
        """
    with closing(sqlite3.connect(CONTENT_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, [agent_text]).fetchall()
    return [row[0] for row in res]


def get_pmids_for_hgnc_id(hgnc_id):
    query = \
        """SELECT
                pmid
            FROM
                entrez_pmids
            WHERE
                hgnc_id = ?;
        """
    with closing(sqlite3.connect(CONTENT_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, [hgnc_id]).fetchall()
    return [row[0] for row in res]


def get_pmids_for_entity(ns, id_, major_topic=False):
    table = 'entity_pmids_major' if major_topic else 'entity_pmids'
    query = \
        f"""SELECT
                pmid
            FROM
                {table}
            WHERE
                grounding = ?;
        """
    with closing(sqlite3.connect(CONTENT_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query,
                              [f'{ns}:{id_}']).fetchall()
    return [row[0] for row in res]


def _get_xmls_for_pmids(pmids):
    pmids = tuple(pmids)
    query = \
        f"""SELECT
                pmid, content
            FROM
                best_content
            WHERE
                pmid IN ({','.join(['?']*len(pmids))})
    """
    with closing(sqlite3.connect(CONTENT_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, pmids).fetchall()
    return [[pmid, _unpack(bytearray.fromhex(content[2:]))]
            for pmid, content in res]


def _unpack(bts, decode=True):
    ret = zlib.decompress(bts, zlib.MAX_WBITS+16)
    if decode:
        ret = ret.decode('utf-8')
    return ret


def get_agent_texts_for_pmids(pmids):
    pmids = tuple(pmids)
    query = \
        f"""SELECT
                pmid, group_concat(agent_text)
            FROM
                agent_text_pmids
            WHERE
                pmid IN ({','.join(['?']*len(pmids))})
            GROUP BY pmid
         """
    with closing(sqlite3.connect(CONTENT_DB_PATH)) as conn:
        with closing(conn.cursor()) as cur:
            res = cur.execute(query, pmids).fetchall()
    return {pmid: dict(Counter(agent_texts.split(',')))
            for pmid, agent_texts in res}


def get_agent_texts_for_entity(ns, id_):
    pmids = get_pmids_for_entity(ns, id_)
    if not pmids:
        return []
    counts = get_agent_texts_for_pmids(pmids)
    return counts


def get_abbreviations(xml):
    try:
        tree = etree.fromstring(xml.encode('utf-8'))
    except Exception:
        return {}
    items = tree.xpath('.//glossary/def-list/def-item')
    result = {}
    for item in items:
        term_elements = item.xpath('./term')
        if not term_elements:
            continue
        term = ''.join(term_elements[0].itertext()).strip()
        def_elements = item.xpath('./def')
        if not def_elements:
            continue
        def_ = ''.join(def_elements[0].itertext()).strip()
        result[term] = def_
    return result
