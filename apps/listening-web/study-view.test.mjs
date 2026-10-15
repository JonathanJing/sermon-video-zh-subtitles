import test from 'node:test';
import assert from 'node:assert/strict';
import { renderMeditation } from './published-weeks.mjs';
function fixture() {
  const document = { createElement(tag) { return { tag, ownerDocument:document, children:[], style:{},
    append(...children) { this.children.push(...children); }, replaceChildren() { this.children=[]; } }; } };
  return document.createElement('section');
}
test('meditation renders every complete title and body as text, preserving newlines', () => {
  const element = fixture();
  const sections = [{title:'<script>title</script>',body:'第一句\n完整经文。'}, {title:'Second',body:'Long body ending remains visible.'}];
  renderMeditation(element, sections, 'zh-Hans');
  assert.equal(element.hidden,false);
  assert.equal(element.children[0].textContent,'默想');
  assert.deepEqual(element.children.slice(1).map(row => row.children.map(item=>item.textContent)), sections.map(row=>[row.title,row.body]));
  assert.equal(element.children[1].children[1].style.whiteSpace,'pre-wrap');
  renderMeditation(element, [], 'es');
  assert.equal(element.hidden,true); assert.deepEqual(element.children,[]);
});
