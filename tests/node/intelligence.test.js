/**
 * Tests for Model Intelligence (MI) score computation.
 * Uses shared test vectors for cross-implementation parity.
 */

const path = require('path');
const fs = require('fs');
const { computeMI, getContextZone } = require('../../scripts/statusline');

const VECTORS_PATH = path.join(__dirname, '..', 'fixtures', 'mi_test_vectors.json');
const vectors = JSON.parse(fs.readFileSync(VECTORS_PATH, 'utf8'));

describe('computeMI', () => {
    test('guard clause: context_window=0 returns MI=1.0', () => {
        const result = computeMI(50000, 0, 'claude-opus-4-6');
        expect(result.mi).toBe(1.0);
    });

    test('empty context returns MI=1.0', () => {
        const result = computeMI(0, 200000, 'claude-sonnet-4-6');
        expect(result.mi).toBe(1.0);
    });

    test('full context is always MI=0.0 regardless of model', () => {
        for (const model of ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5']) {
            const result = computeMI(200000, 200000, model);
            expect(result.mi).toBe(0);
        }
    });

    test('unknown model uses default (sonnet) profile', () => {
        const result = computeMI(100000, 200000, 'unknown-model');
        const sonnet = computeMI(100000, 200000, 'claude-sonnet-4-6');
        expect(result.mi).toBeCloseTo(sonnet.mi, 2);
    });

    test('beta override takes precedence', () => {
        // Opus with beta_override=1.0: MI = 1 - 0.5^1.0 = 0.5
        const result = computeMI(100000, 200000, 'claude-opus-4-6', 1.0);
        expect(result.mi).toBeCloseTo(0.5, 2);
    });

    test('MI is always between 0 and 1', () => {
        const utilizations = [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0];
        for (const u of utilizations) {
            const used = Math.floor(u * 200000);
            const result = computeMI(used, 200000, 'claude-sonnet-4-6');
            expect(result.mi).toBeGreaterThanOrEqual(0);
            expect(result.mi).toBeLessThanOrEqual(1);
        }
    });

    test('opus degrades less than sonnet at same utilization', () => {
        const opus = computeMI(140000, 200000, 'claude-opus-4-6');
        const sonnet = computeMI(140000, 200000, 'claude-sonnet-4-6');
        expect(opus.mi).toBeGreaterThan(sonnet.mi);
    });
});

// --- Context zone tests ---

describe('getContextZone', () => {
    // 1M model tests
    test('1M model, 50k used → P (green)', () => {
        const z = getContextZone(50000, 1000000);
        expect(z.zone).toBe('P');
        expect(z.colorName).toBe('green');
    });

    test('1M model, 85k used → C (yellow)', () => {
        const z = getContextZone(85000, 1000000);
        expect(z.zone).toBe('C');
        expect(z.colorName).toBe('yellow');
    });

    test('1M model, 150k used → D (orange)', () => {
        const z = getContextZone(150000, 1000000);
        expect(z.zone).toBe('D');
        expect(z.colorName).toBe('orange');
    });

    test('1M model, 250k used → X (dark_red)', () => {
        const z = getContextZone(250000, 1000000);
        expect(z.zone).toBe('X');
        expect(z.colorName).toBe('dark_red');
    });

    test('1M model, 300k used → Z (gray)', () => {
        const z = getContextZone(300000, 1000000);
        expect(z.zone).toBe('Z');
        expect(z.colorName).toBe('gray');
    });

    // Boundary tests
    test('boundary: 70k → C (not P)', () => {
        expect(getContextZone(70000, 1000000).zone).toBe('C');
        expect(getContextZone(69999, 1000000).zone).toBe('P');
    });

    test('boundary: 100k → D (not C)', () => {
        expect(getContextZone(100000, 1000000).zone).toBe('D');
        expect(getContextZone(99999, 1000000).zone).toBe('C');
    });

    test('boundary: 275k → Z (past X), X is 250k–275k range', () => {
        expect(getContextZone(275000, 1000000).zone).toBe('Z');
        expect(getContextZone(274999, 1000000).zone).toBe('X');
        // 250001 is now within X range (not Z)
        expect(getContextZone(250001, 1000000).zone).toBe('X');
    });

    // Standard model tests
    test('200k model, 20k used → P', () => {
        expect(getContextZone(20000, 200000).zone).toBe('P');
    });

    test('200k model, 60k used → C', () => {
        expect(getContextZone(60000, 200000).zone).toBe('C');
    });

    test('200k model, 100k (50%) → D', () => {
        expect(getContextZone(100000, 200000).zone).toBe('D');
    });

    test('200k model, 140k (70%) → X', () => {
        expect(getContextZone(140000, 200000).zone).toBe('X');
    });

    test('200k model, 150k (75%) → Z', () => {
        expect(getContextZone(150000, 200000).zone).toBe('Z');
    });

    // Guard clause
    test('context_window=0 → P', () => {
        expect(getContextZone(50000, 0).zone).toBe('P');
    });

    // Large model threshold
    test('500k context is treated as 1M-class', () => {
        expect(getContextZone(50000, 500000).zone).toBe('P');
    });
});

describe('shared test vectors', () => {
    vectors.forEach((vec) => {
        test(vec.description, () => {
            const inp = vec.input;
            const exp = vec.expected;

            const betaOverride = inp.beta_override || 0;

            const result = computeMI(
                inp.current_used,
                inp.context_window,
                inp.model_id,
                betaOverride
            );

            expect(result.mi).toBeCloseTo(exp.mi, 1);
        });
    });
});
