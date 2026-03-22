const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const SCRIPT_PATH = path.join(__dirname, '..', '..', 'scripts', 'statusline.js');
const FIXTURES_DIR = path.join(__dirname, '..', 'fixtures', 'json');

/**
 * Strip ANSI escape sequences from a string
 */
function stripAnsi(s) {
    return s.replace(/\x1b\[[0-9;]*m/g, '');
}

/**
 * Run the statusline.js script with the given input data
 * @param {Object|string} inputData - JSON input or string
 * @param {Object} [envOverrides] - Optional environment variable overrides
 * @returns {Promise<{stdout: string, stderr: string, code: number}>}
 */
function runScript(inputData, envOverrides) {
    return new Promise((resolve, reject) => {
        const env = { ...process.env, ...envOverrides };
        const child = spawn('node', [SCRIPT_PATH], { env });
        let stdout = '';
        let stderr = '';

        child.stdout.on('data', data => {
            stdout += data.toString();
        });

        child.stderr.on('data', data => {
            stderr += data.toString();
        });

        child.on('close', code => {
            resolve({ stdout: stdout.trim(), stderr, code });
        });

        child.on('error', reject);

        const input = typeof inputData === 'string' ? inputData : JSON.stringify(inputData);
        child.stdin.write(input);
        child.stdin.end();
    });
}

/**
 * Load a JSON fixture file
 * @param {string} name - Fixture name without .json extension
 * @returns {Object}
 */
function loadFixture(name) {
    const filePath = path.join(FIXTURES_DIR, `${name}.json`);
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

describe('statusline.js', () => {
    const sampleInput = {
        model: { display_name: 'Claude 3.5 Sonnet' },
        workspace: {
            current_dir: '/home/user/myproject',
            project_dir: '/home/user/myproject',
        },
        context_window: {
            context_window_size: 200000,
            current_usage: {
                input_tokens: 10000,
                cache_creation_input_tokens: 500,
                cache_read_input_tokens: 200,
            },
        },
    };

    describe('Script basics', () => {
        test('script file exists', () => {
            expect(fs.existsSync(SCRIPT_PATH)).toBe(true);
        });

        test('script has node shebang', () => {
            const content = fs.readFileSync(SCRIPT_PATH, 'utf8');
            expect(content.startsWith('#!/usr/bin/env node')).toBe(true);
        });
    });

    describe('Output content', () => {
        test('outputs model name', async () => {
            const result = await runScript(sampleInput);
            expect(result.stdout).toContain('Claude 3.5 Sonnet');
            expect(result.code).toBe(0);
        });

        test('outputs directory name', async () => {
            const result = await runScript(sampleInput);
            expect(result.stdout).toContain('myproject');
        });

        test('shows free tokens indicator', async () => {
            const result = await runScript(sampleInput);
            expect(result.stdout).toContain('%');
        });

        test('AC indicator removed from statusline', async () => {
            const result = await runScript(sampleInput);
            expect(result.stdout).not.toContain('[AC:');
        });

        test('shows percentage', async () => {
            const result = await runScript(sampleInput);
            expect(result.stdout).toMatch(/\d+\.\d+%/);
        });
    });

    describe('Error handling', () => {
        test('handles missing model gracefully', async () => {
            const input = {
                workspace: { current_dir: '/tmp/test', project_dir: '/tmp/test' },
            };
            const result = await runScript(input);
            expect(result.stdout).toContain('Claude'); // Default fallback
            expect(result.code).toBe(0);
        });

        test('handles missing context window gracefully', async () => {
            const input = {
                model: { display_name: 'Claude' },
                workspace: { current_dir: '/tmp/test', project_dir: '/tmp/test' },
            };
            const result = await runScript(input);
            expect(result.code).toBe(0);
        });

        test('handles invalid JSON gracefully', async () => {
            const result = await runScript('invalid json');
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('Claude');
        });

        test('handles empty input gracefully', async () => {
            const result = await runScript('');
            expect(result.code).toBe(0);
        });
    });

    describe('Fixtures', () => {
        test('handles valid_full fixture', async () => {
            const input = loadFixture('valid_full');
            const result = await runScript(input);
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('Opus 4.5');
            expect(result.stdout).toContain('my-project');
        });

        test('handles valid_minimal fixture', async () => {
            const input = loadFixture('valid_minimal');
            const result = await runScript(input);
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('Claude');
        });

        test('handles low_usage fixture', async () => {
            const input = loadFixture('low_usage');
            const result = await runScript(input);
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('%');
        });

        test('handles medium_usage fixture', async () => {
            const input = loadFixture('medium_usage');
            const result = await runScript(input);
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('%');
        });

        test('handles high_usage fixture', async () => {
            const input = loadFixture('high_usage');
            const result = await runScript(input);
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('%');
        });

        test('all JSON fixtures succeed', async () => {
            const fixtures = fs.readdirSync(FIXTURES_DIR).filter(f => f.endsWith('.json'));
            for (const fixture of fixtures) {
                const input = JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, fixture), 'utf8'));
                const result = await runScript(input);
                expect(result.code).toBe(0);
            }
        });
    });

    describe('Session ID display', () => {
        test('shows session_id by default', async () => {
            const inputWithSession = {
                ...sampleInput,
                session_id: 'test-session-abc123',
            };
            const result = await runScript(inputWithSession, { COLUMNS: '200' });
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('test-session-abc123');
        });

        test('handles missing session_id gracefully', async () => {
            const result = await runScript(sampleInput);
            expect(result.code).toBe(0);
        });
    });

    describe('Width truncation', () => {
        test('output fits 80 columns', async () => {
            const inputWithSession = {
                ...sampleInput,
                session_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            };
            const result = await runScript(inputWithSession, { COLUMNS: '80' });
            expect(result.code).toBe(0);
            const visible = stripAnsi(result.stdout);
            expect(visible.length).toBeLessThanOrEqual(80);
        });

        test('narrow terminal drops parts', async () => {
            const result = await runScript(sampleInput, { COLUMNS: '40' });
            expect(result.code).toBe(0);
            const visible = stripAnsi(result.stdout);
            expect(visible.length).toBeLessThanOrEqual(40);
            expect(visible).toContain('myproject');
            // Model name is lowest priority — truncated first in narrow terminals
            expect(visible).not.toContain('Claude 3.5 Sonnet');
        });

        test('wide terminal shows all', async () => {
            const inputWithSession = {
                ...sampleInput,
                session_id: 'test-wide-session-uuid',
            };
            const result = await runScript(inputWithSession, { COLUMNS: '200' });
            expect(result.code).toBe(0);
            expect(result.stdout).toContain('test-wide-session-uuid');
        });
    });
});
