import test from 'node:test';
import assert from 'node:assert/strict';
import { categoryLabel, fullReadingRows, findEnglishPositions, ReadingFollow } from './reading-mode.mjs';

test('category follows interface locale with simplified Chinese and English fallback', () => {
  const category = {schemaVersion:'sermon-page-display-category-v1', labels:{'zh-Hans':'正式播放版', en:'Archive', ko:'설교'}};
  assert.equal(categoryLabel(category, 'zh'), '正式播放版');
  assert.equal(categoryLabel(category, 'zh-CN'), '正式播放版');
  assert.equal(categoryLabel(category, 'ko-KR'), '설교');
  assert.equal(categoryLabel(category, 'es'), 'Archive');
  assert.equal(categoryLabel({...category, labels:{en:'bad\nlabel'}}, 'en'), null);
  assert.equal(categoryLabel({...category, labels:{'zh-Hans':'仅中文'}}, 'zh'), null);
});
test('full text seeks the audio group clock and refuses ambiguous or missing bindings', () => {
  const full = [{textGroupId:'a',start:100,text:'complete text'}, {textGroupId:'b',start:200}];
  const audio = [{textGroupId:'a',start:5,end:10,text:'short dub'}];
  assert.equal(fullReadingRows(full,audio)[0].audioCue.start,5);
  assert.equal(fullReadingRows(full,audio)[1].audioCue,null);
  assert.equal(fullReadingRows(full,[...audio,...audio])[0].audioCue,null);
});
test('free reading stops automatic scrolling; return only scrolls even when paused', () => {
  const follow = new ReadingFollow(); let scrolls = 0;
  const scroll = () => { scrolls += 1; };
  follow.update({active:true,playing:true,changed:true},scroll);
  follow.userScroll(); follow.update({active:true,playing:true,changed:true},scroll);
  assert.equal(scrolls,1);
  follow.returnToCurrent(scroll); assert.equal(scrolls,2); assert.equal(follow.following,true);
  follow.update({active:true,playing:false,changed:true},scroll); assert.equal(scrolls,2);
});
test('English locate searches actual reference text and preserves exact mapped audio time', () => {
  const rows=[{english:'Jesus is worthy.',time:7}, {english:null,time:12}];
  assert.deepEqual(findEnglishPositions(rows,'JESUS worthy'),[rows[0]]);
  assert.deepEqual(findEnglishPositions(rows,''),[]);
});
