import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('client bundle registers the production-progress dock entry', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  let handoff = null
  const window = {
    __ModuleLoader__: {
      load(value) { handoff = value },
    },
  }
  // eslint-disable-next-line no-new-func
  const execute = new Function('window', source)
  execute(window)
  assert.ok(handoff)
  assert.equal(handoff.id, 'dsh-production-progress')

  const fakeReact = {
    createElement() {},
    useState() {},
    useEffect() {},
  }
  const exports = handoff.factory(spec => {
    if (spec === 'react') return fakeReact
    throw new Error(`unexpected require ${spec}`)
  })
  assert.deepEqual(exports.inject, ['slots'])
  assert.equal(typeof exports.apply, 'function')
  assert.equal(typeof exports.Dock, 'function')

  let injected = null
  let registered = null
  const ctx = {
    slots: {
      inject(name, factory) { injected = name; factory() },
      register(options, component) { registered = { options, component }; return () => {} },
    },
  }
  exports.apply(ctx)
  assert.equal(injected, 'conversation.input.dock')
  assert.equal(registered.options.id, 'production-progress')
  assert.equal(registered.options.order, 16)
  assert.equal(registered.component, exports.Dock)
})
