import { describe, expect, it } from 'vitest';
import { asArray } from '../lib/utils';

describe('asArray', () => {
  it('extracts a keyed array from an object response', () => {
    expect(asArray({ events: [1, 2, 3] }, 'events')).toEqual([1, 2, 3]);
  });

  it('returns a bare array as-is', () => {
    expect(asArray([1, 2], 'events')).toEqual([1, 2]);
    expect(asArray([1, 2])).toEqual([1, 2]);
  });

  it('returns [] when the keyed value is missing or not an array (the crash guard)', () => {
    expect(asArray({ detail: 'error' }, 'events')).toEqual([]); // error envelope
    expect(asArray({ events: null }, 'events')).toEqual([]);
    expect(asArray({ events: { not: 'array' } }, 'events')).toEqual([]);
  });

  it('returns [] for non-array / nullish input', () => {
    expect(asArray(null, 'events')).toEqual([]);
    expect(asArray(undefined)).toEqual([]);
    expect(asArray('string')).toEqual([]);
    expect(asArray(42, 'events')).toEqual([]);
  });

  it('returns [] for an object when no key is given', () => {
    expect(asArray({ events: [1] })).toEqual([]); // no key → not an array → []
  });
});
