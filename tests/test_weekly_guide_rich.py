"""Synthetic fixtures exercise source-bound layout, not licensed manual text."""
import copy
import hashlib
import json
import pytest
from tongxing_production.delivery import weekly_guide_rich as r


def test_independent_lists_and_two_arrows_do_not_become_false_pairs():
    body = ('A heading\nA description\n\n| A | B |\n|---|---|\n| One | Two |\n\n'
            'Another heading\nAnother description\n\n| Days | | "Trumpets" | |\n|---|---|---|---|\n'
            '| D1 | Light | T1 | Land |\n| D2 | Water | T2 | Sea |\n'
            '| D3 | Land | T3 | Rivers |\n| D4 | Stars | T4 | Dark |\n\n'
            'Creation的次序：Light → Water → Land\n"Trumpets"的次序：Land → Water → Light')
    blocks, fallback = r._page83(body)
    assert [x['type'] for x in blocks] == ['paragraph','table','paragraph','list','list','flow','flow']
    assert blocks[3]['items'] == ['D1：Light','D2：Water','D3：Land','D4：Stars']
    assert blocks[4]['items'] == ['T1：Land','T2：Sea','T3：Rivers','T4：Dark']
    assert fallback.index('D4：Stars') < fallback.index('T1：Land')
    assert blocks[5]['items'] == ['Light','Water','Land']
    assert blocks[6]['items'] == ['Land','Water','Light']
    assert 'D1：Light\nT1：Land' not in fallback


def test_merged_final_row_is_not_rendered_as_two_comparison_cells():
    body = '| | A | B |\n|---|---|---|\n' + ''.join(f'| {i} | a{i} | b{i} |\n' for i in range(6)) + '| final | first part | second part |'
    blocks = r._page_blocks(body,123)
    assert len(blocks[0]['rows']) == 6
    assert blocks[1] == {'type':'paragraph','text':'final：first part second part'}


def test_page140_keeps_each_group_in_order_and_legacy_body_unchanged():
    body = ('Title\nSubtitle\n\nPlaces\n- A (ref A)\n- B (ref B)\n- C (ref C)\n\n'
            'Pattern (ref D)\n- D\n- E\n- F\n- G\n- H')
    blocks = r._page140(body)
    assert blocks == [{'type':'paragraph','text':'Title\nSubtitle'},
                      {'type':'list','title':'Places','items':['A (ref A)','B (ref B)','C (ref C)']},
                      {'type':'list','title':'Pattern (ref D)','items':['D','E','F','G','H']}]
    guide = {'week':10,'sections':[{'id':'page-140','title':'old','body':body}]}
    revision = {'entries':{140:{'week':10,'expectedOriginalBodySHA256':r.digest(body.encode()),'blocks':blocks}}}
    section = r.apply_revision(guide,revision)['sections'][0]
    assert section['body'] == body
    assert section['blocks'] == blocks


def test_comparisons_keep_column_relationships_and_legacy_body():
    first = 'Heading\n\nVerses\n\nQuote\n\n• Left vs. Right\nleft verse\nright verse'
    second = '• A vs. B\nfirst left\nfirst right\n\n• C vs. D\nsecond left\nsecond right'
    blocks = r._page138_139(first,138)
    assert [x['type'] for x in blocks] == ['paragraph','paragraph','paragraph','table']
    assert blocks[-1] == {'type':'table','title':'','columns':['Left','Right'],
                          'rows':[['left verse','right verse']]}
    assert r._page138_139(second,139) == [
        {'type':'table','title':'','columns':['A','B'],'rows':[['first left','first right']]},
        {'type':'table','title':'','columns':['C','D'],'rows':[['second left','second right']]}]
    guide = {'week':10,'sections':[{'id':'page-138','title':'old','body':first}]}
    revision = {'entries':{138:{'week':10,'expectedOriginalBodySHA256':r.digest(first.encode()),'blocks':blocks}}}
    assert r.apply_revision(guide,revision)['sections'][0]['body'] == first
    for bad in (second.replace(' vs. ', ' or ', 1), second.replace('first right\n', ''), second+'\nextra'):
        with pytest.raises(ValueError,match='unexpected comparison'):
            r._page138_139(bad,139)


@pytest.mark.parametrize('block', [
    {'type':'table','title':'x','columns':['a','b'],'rows':[['one']]},
    {'type':'list','title':'x','items':[]},
    {'type':'flow','title':'x','items':['a',3]},
    {'type':'image','assetID':'../../outside','alt':'x','caption':'x'},
    {'type':'unknown','text':'x'},
])
def test_unsupported_or_malformed_blocks_fail_whole_section(block):
    with pytest.raises(ValueError, match='invalid or unsupported'):
        r.validate_blocks([block])


def test_revision_requires_original_body_and_keeps_corrected_legacy_fallback():
    original = {'id':'sample','week':5,'sections':[{'id':'page-83','title':'old',
                'subtitle':'p','symbol':'doc.text','body':'wrong-pair-body'}]}
    body_hash = hashlib.sha256(b'wrong-pair-body').hexdigest()
    revision = {'entries':{83:{'week':5,'expectedOriginalBodySHA256':body_hash,
                 'correctedFallbackBody':'two independent lists',
                 'blocks':[{'type':'paragraph','text':'two independent lists'}]}}}
    amended = r.apply_revision(original,revision)
    assert original['sections'][0]['body'] == 'wrong-pair-body'
    assert amended['sections'][0]['body'] == 'two independent lists'
    assert amended['sections'][0]['blocks'][0]['text'] == amended['sections'][0]['body']
    changed = copy.deepcopy(original);changed['sections'][0]['body'] = 'another-body'
    with pytest.raises(ValueError,match='original guide body'):
        r.apply_revision(changed,revision)
    changed = copy.deepcopy(original);changed['week'] = 6
    with pytest.raises(ValueError,match='original guide body'):
        r.apply_revision(changed,revision)


def test_images_use_only_fixed_assets_and_legacy_text_stays_available():
    guide = {'week':1,'sections':[{'id':'page-31','title':'source','subtitle':'p',
             'symbol':'doc.text','body':'figure description'}]}
    amended = r.apply_revision(guide,{'entries':{}},include_images=True)
    assert amended['sections'][0]['body'] == 'figure description'
    assert amended['sections'][0]['blocks'][1]['assetID'] == 'weekly-guide-statue.jpg'
    r.validate_blocks(amended['sections'][0]['blocks'])


def test_map_uses_representative_points_and_keeps_fallback():
    guide = {'week':1,'sections':[{'id':'page-33','title':'source','subtitle':'p',
             'symbol':'doc.text','body':'original map description'}]}
    credits = {source:'作者：A；贡献者：B' for _,_,_,source in r.MAP_POINTS}
    section = r.apply_revision(guide,{'entries':{}},include_images=True,map_credits=credits)['sections'][0]
    assert section['body'] == 'original map description'
    map_block = section['blocks'][0]
    assert len(map_block['points']) == 8
    assert '并非教会建筑精确位置' in map_block['caption']
    assert 'CC BY 3.0' in map_block['attribution']
    assert all(point['credit'] == '作者：A；贡献者：B' for point in map_block['points'])
    r.validate_blocks(section['blocks'])
    for mutate in (
        lambda m: m['points'][0].update(sourceURL='https://example.com/places/1'),
        lambda m: m['points'][0].update(latitude=float('nan')),
        lambda m: m.update(points=m['points'][:1]),
    ):
        invalid = copy.deepcopy(map_block)
        mutate(invalid)
        with pytest.raises(ValueError, match='invalid or unsupported'):
            r.validate_blocks([invalid])


def test_map_evidence_checks_each_source_bytes_and_coordinates(tmp_path, monkeypatch):
    points = []
    (tmp_path / 'pleiades').mkdir()
    for name, latitude, longitude, source in r.MAP_POINTS:
        raw = json.dumps({'reprPoint':[longitude,latitude], 'creators':[{'name':'A'}],
                          'contributors':[{'name':'B'},{'name':'C'}]}).encode()
        (tmp_path / 'pleiades' / f'{source}.json').write_bytes(raw)
        uri = 'https://pleiades.stoa.org/places/' + source
        points.append({'uri':uri,'chinese':name,'latitude':latitude,'longitude':longitude,
                       'jsonURL':uri+'/json','sourceJSONSHA256':r.digest(raw)})
    manifest = json.dumps({'schemaVersion':'tongxing-pleiades-map-research-v1',
                           'license':'CC BY 3.0','points':points}).encode()
    (tmp_path / 'map-points.json').write_bytes(manifest)
    monkeypatch.setattr(r,'MAP_EVIDENCE_SHA256',r.digest(manifest))
    actual_digest, credits = r.validate_map_evidence(tmp_path)
    assert actual_digest == r.digest(manifest)
    assert credits['550812'] == '作者：A；贡献者：B, C'
    (tmp_path / 'pleiades' / '550812.json').write_text('{}')
    with pytest.raises(ValueError, match='source content mismatch'):
        r.validate_map_evidence(tmp_path)


def test_non_page_scripture_title_is_preserved():
    guide={'week':5,'sections':[{'id':'scripture-cuv1919','title':'Bible',
           'subtitle':'source','symbol':'book','body':'1:1 text'}]}
    assert r.apply_revision(guide,{'entries':{}})['sections'][0]['title']=='Bible'
