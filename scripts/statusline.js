#!/usr/bin/env node
/**
 * Node.js status line script for Claude Code
 * Usage: Copy to ~/.claude/statusline.js and make executable
 *
 * Configuration:
 * Create/edit ~/.claude/statusline.conf and set:
 *
 *   autocompact=true   (when autocompact is enabled in Claude Code - default)
 *   autocompact=false  (when you disable autocompact via /config in Claude Code)
 *
 *   token_detail=true  (show exact token count like 64,000 - default)
 *   token_detail=false (show abbreviated tokens like 64.0k)
 *
 *   show_delta=true    (show token delta since last refresh like [+2,500] - default)
 *   show_delta=false   (disable delta display - saves file I/O on every refresh)
 *
 *   show_session=true  (show session_id in status line - default)
 *   show_session=false (hide session_id from status line)
 *
 * When AC is enabled, 22.5% of context window is reserved for autocompact buffer.
 *
 * State file format (CSV):
 *   timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,
 *   current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,
 *   total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,
 *   workspace_project_dir
 */

const { execSync } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const os = require('os');

const ROTATION_THRESHOLD = 10000;
const ROTATION_KEEP = 5000;

/**
 * Rotate a state file if it exceeds ROTATION_THRESHOLD lines.
 * Keeps the most recent ROTATION_KEEP lines via atomic temp-file + rename.
 */
function maybeRotateStateFile(stateFile) {
    try {
        if (!fs.existsSync(stateFile)) {
            return;
        }
        const content = fs.readFileSync(stateFile, 'utf8');
        const lines = content.split('\n');
        // Remove trailing empty element from split if file ends with newline
        if (lines.length > 0 && lines[lines.length - 1] === '') {
            lines.pop();
        }
        if (lines.length <= ROTATION_THRESHOLD) {
            return;
        }
        const keep = lines.slice(-ROTATION_KEEP);
        const tmpFile = stateFile + '.' + crypto.randomBytes(6).toString('hex') + '.tmp';
        try {
            fs.writeFileSync(tmpFile, keep.join('\n') + '\n');
            fs.renameSync(tmpFile, stateFile);
        } catch (e) {
            try {
                fs.unlinkSync(tmpFile);
            } catch {
                /* cleanup best-effort */
            }
            throw e;
        }
    } catch (e) {
        process.stderr.write(`[statusline] warning: failed to rotate state file: ${e.message}\n`);
    }
}

// ANSI Colors
const BLUE = '\x1b[0;34m';
const MAGENTA = '\x1b[0;35m';
const CYAN = '\x1b[0;36m';
const GREEN = '\x1b[0;32m';
const YELLOW = '\x1b[0;33m';
const RED = '\x1b[0;31m';
const DIM = '\x1b[2m';
const RESET = '\x1b[0m';

/**
 * Return the visible width of a string after stripping ANSI escape sequences.
 */
function visibleWidth(s) {
    // eslint-disable-next-line no-control-regex
    return s.replace(/\x1b\[[0-9;]*m/g, '').length;
}

/**
 * Return the terminal width in columns, defaulting to 80.
 */
function getTerminalWidth() {
    return process.stdout.columns || parseInt(process.env.COLUMNS, 10) || 80;
}

/**
 * Assemble parts into a single line that fits within maxWidth.
 * Parts are added in priority order (first = highest priority).
 * The first part (base) is always included.
 */
function fitToWidth(parts, maxWidth) {
    if (!parts.length) {
        return '';
    }

    let result = parts[0];
    let currentWidth = visibleWidth(result);

    for (let i = 1; i < parts.length; i++) {
        const part = parts[i];
        if (!part) {
            continue;
        }
        const partWidth = visibleWidth(part);
        if (currentWidth + partWidth <= maxWidth) {
            result += part;
            currentWidth += partWidth;
        }
    }

    return result;
}

function getGitInfo(projectDir) {
    const gitDir = path.join(projectDir, '.git');
    if (!fs.existsSync(gitDir) || !fs.statSync(gitDir).isDirectory()) {
        return '';
    }

    try {
        // Get branch name (skip optional locks for performance)
        const branch = execSync('git --no-optional-locks rev-parse --abbrev-ref HEAD', {
            cwd: projectDir,
            encoding: 'utf8',
            stdio: ['pipe', 'pipe', 'pipe'],
            timeout: 5000,
        }).trim();

        if (!branch) {
            return '';
        }

        // Count changes
        const status = execSync('git --no-optional-locks status --porcelain', {
            cwd: projectDir,
            encoding: 'utf8',
            stdio: ['pipe', 'pipe', 'pipe'],
            timeout: 5000,
        });
        const changes = status.split('\n').filter(l => l.trim()).length;

        if (changes > 0) {
            return ` | ${MAGENTA}${branch}${RESET} ${CYAN}[${changes}]${RESET}`;
        }
        return ` | ${MAGENTA}${branch}${RESET}`;
    } catch {
        return '';
    }
}

function readConfig() {
    const config = {
        autocompact: true,
        tokenDetail: true,
        showDelta: true,
        showSession: true,
        showIoTokens: true,
        reducedMotion: false,
    };
    const configPath = path.join(os.homedir(), '.claude', 'statusline.conf');

    // Create config file with defaults if it doesn't exist
    if (!fs.existsSync(configPath)) {
        try {
            const configDir = path.dirname(configPath);
            if (!fs.existsSync(configDir)) {
                fs.mkdirSync(configDir, { recursive: true });
            }
            const defaultConfig = `# Autocompact setting - sync with Claude Code's /config
autocompact=true

# Token display format
token_detail=true

# Show token delta since last refresh (adds file I/O on every refresh)
# Disable if you don't need it to reduce overhead
show_delta=true

# Show session_id in status line
show_session=true
`;
            fs.writeFileSync(configPath, defaultConfig);
        } catch (e) {
            process.stderr.write(`[statusline] warning: failed to create config: ${e.message}\n`);
        }
        return config;
    }

    try {
        const content = fs.readFileSync(configPath, 'utf8');
        for (const line of content.split('\n')) {
            const trimmed = line.trim();
            if (trimmed.startsWith('#') || !trimmed.includes('=')) {
                continue;
            }
            const [key, value] = trimmed.split('=', 2);
            const keyTrimmed = key.trim();
            const valueTrimmed = value.trim().toLowerCase();
            if (keyTrimmed === 'autocompact') {
                config.autocompact = valueTrimmed !== 'false';
            } else if (keyTrimmed === 'token_detail') {
                config.tokenDetail = valueTrimmed !== 'false';
            } else if (keyTrimmed === 'show_delta') {
                config.showDelta = valueTrimmed !== 'false';
            } else if (keyTrimmed === 'show_session') {
                config.showSession = valueTrimmed !== 'false';
            } else if (keyTrimmed === 'show_io_tokens') {
                config.showIoTokens = valueTrimmed !== 'false';
            } else if (keyTrimmed === 'reduced_motion') {
                config.reducedMotion = valueTrimmed !== 'false';
            }
        }
    } catch (e) {
        process.stderr.write(`[statusline] warning: failed to read config: ${e.message}\n`);
    }
    return config;
}

let input = '';

process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => (input += chunk));

process.stdin.on('end', () => {
    let data;
    try {
        data = JSON.parse(input);
    } catch {
        console.log('[Claude] ~');
        return;
    }

    // Extract data
    const cwd = data.workspace?.current_dir || '~';
    const projectDir = data.workspace?.project_dir || cwd;
    const model = data.model?.display_name || 'Claude';
    const dirName = path.basename(cwd) || '~';

    // Git info
    const gitInfo = getGitInfo(projectDir);

    // Read settings from config file
    const config = readConfig();
    const autocompactEnabled = config.autocompact;
    const tokenDetail = config.tokenDetail;
    const showDelta = config.showDelta;
    const showSession = config.showSession;
    // Note: showIoTokens setting is read but not yet implemented

    // Extract session_id once for reuse
    const sessionId = data.session_id;

    // Context window calculation
    let contextInfo = '';
    let acInfo = '';
    let deltaInfo = '';
    let sessionInfo = '';
    const totalSize = data.context_window?.context_window_size || 0;
    const currentUsage = data.context_window?.current_usage;
    const totalInputTokens = data.context_window?.total_input_tokens || 0;
    const totalOutputTokens = data.context_window?.total_output_tokens || 0;
    const costUsd = data.cost?.total_cost_usd || 0;
    const linesAdded = data.cost?.total_lines_added || 0;
    const linesRemoved = data.cost?.total_lines_removed || 0;
    const modelId = data.model?.id || '';
    const workspaceProjectDir = data.workspace?.project_dir || '';

    if (totalSize > 0 && currentUsage) {
        // Get tokens from current_usage (includes cache)
        const inputTokens = currentUsage.input_tokens || 0;
        const cacheCreation = currentUsage.cache_creation_input_tokens || 0;
        const cacheRead = currentUsage.cache_read_input_tokens || 0;

        // Total used from current request
        const usedTokens = inputTokens + cacheCreation + cacheRead;

        // Calculate autocompact buffer (22.5% of context window = 45k for 200k)
        const autocompactBuffer = Math.floor(totalSize * 0.225);

        // Free tokens calculation depends on autocompact setting
        let freeTokens;
        if (autocompactEnabled) {
            // When AC enabled: subtract buffer to show actual usable space
            freeTokens = totalSize - usedTokens - autocompactBuffer;
            const bufferK = Math.floor(autocompactBuffer / 1000);
            acInfo = ` ${DIM}[AC:${bufferK}k]${RESET}`;
        } else {
            // When AC disabled: show full free space
            freeTokens = totalSize - usedTokens;
            acInfo = ` ${DIM}[AC:off]${RESET}`;
        }

        if (freeTokens < 0) {
            freeTokens = 0;
        }

        // Calculate percentage with one decimal (relative to total size)
        const freePct = (freeTokens * 100.0) / totalSize;
        const freePctInt = Math.floor(freePct);

        // Format tokens based on token_detail setting
        const freeDisplay = tokenDetail
            ? freeTokens.toLocaleString('en-US')
            : `${(freeTokens / 1000).toFixed(1)}k`;

        // Color based on free percentage
        let ctxColor;
        if (freePctInt > 50) {
            ctxColor = GREEN;
        } else if (freePctInt > 25) {
            ctxColor = YELLOW;
        } else {
            ctxColor = RED;
        }

        contextInfo = ` | ${ctxColor}${freeDisplay} free (${freePct.toFixed(1)}%)${RESET}`;

        // Calculate and display token delta if enabled
        if (showDelta) {
            const stateDir = path.join(os.homedir(), '.claude', 'statusline');
            if (!fs.existsSync(stateDir)) {
                fs.mkdirSync(stateDir, { recursive: true });
            }

            const oldStateDir = path.join(os.homedir(), '.claude');
            try {
                const oldFiles = fs
                    .readdirSync(oldStateDir)
                    .filter(f => f.match(/^statusline.*\.state$/));
                for (const fileName of oldFiles) {
                    const oldFile = path.join(oldStateDir, fileName);
                    const newFile = path.join(stateDir, fileName);
                    if (fs.statSync(oldFile).isFile()) {
                        if (!fs.existsSync(newFile)) {
                            fs.renameSync(oldFile, newFile);
                        } else {
                            fs.unlinkSync(oldFile);
                        }
                    }
                }
            } catch {
                /* migration errors are non-fatal */
            }

            const stateFileName = sessionId ? `statusline.${sessionId}.state` : 'statusline.state';
            const stateFile = path.join(stateDir, stateFileName);
            let hasPrev = false;
            let prevTokens = 0;
            try {
                if (fs.existsSync(stateFile)) {
                    hasPrev = true;
                    // Read last line to get previous context usage
                    const content = fs.readFileSync(stateFile, 'utf8').trim();
                    const lines = content.split('\n');
                    const lastLine = lines[lines.length - 1];
                    if (lastLine.includes(',')) {
                        const parts = lastLine.split(',');
                        // Calculate previous context usage:
                        // cur_input + cache_creation + cache_read
                        // CSV indices: cur_in[3], cache_create[5], cache_read[6]
                        const prevCurInput = parseInt(parts[3], 10) || 0;
                        const prevCacheCreation = parseInt(parts[5], 10) || 0;
                        const prevCacheRead = parseInt(parts[6], 10) || 0;
                        prevTokens = prevCurInput + prevCacheCreation + prevCacheRead;
                    } else {
                        // Old format - single value
                        prevTokens = parseInt(lastLine, 10) || 0;
                    }
                }
            } catch (e) {
                process.stderr.write(
                    `[statusline] warning: failed to read state file: ${e.message}\n`
                );
                prevTokens = 0;
            }
            // Calculate delta (difference in context window usage)
            const delta = usedTokens - prevTokens;
            // Only show positive delta (and skip first run when no previous state)
            if (hasPrev && delta > 0) {
                const deltaDisplay = tokenDetail
                    ? delta.toLocaleString('en-US')
                    : `${(delta / 1000).toFixed(1)}k`;
                deltaInfo = ` ${DIM}[+${deltaDisplay}]${RESET}`;
            }
            // Only append if context usage changed (avoid duplicates from multiple refreshes)
            if (!hasPrev || usedTokens !== prevTokens) {
                // Append current usage with comprehensive format
                // Format: ts,total_in,total_out,cur_in,cur_out,cache_create,cache_read,
                //         cost_usd,lines_added,lines_removed,session_id,model_id,project_dir
                try {
                    const timestamp = Math.floor(Date.now() / 1000);
                    const curInputTokens = currentUsage.input_tokens || 0;
                    const curOutputTokens = currentUsage.output_tokens || 0;
                    const stateData = [
                        timestamp,
                        totalInputTokens,
                        totalOutputTokens,
                        curInputTokens,
                        curOutputTokens,
                        cacheCreation,
                        cacheRead,
                        costUsd,
                        linesAdded,
                        linesRemoved,
                        sessionId || '',
                        modelId,
                        workspaceProjectDir.replace(/,/g, '_'),
                        totalSize,
                    ].join(',');
                    fs.appendFileSync(stateFile, `${stateData}\n`);
                    maybeRotateStateFile(stateFile);
                } catch (e) {
                    process.stderr.write(
                        `[statusline] warning: failed to write state file: ${e.message}\n`
                    );
                }
            }
        }
    }

    // Display session_id if enabled
    if (showSession && sessionId) {
        sessionInfo = ` ${DIM}${sessionId}${RESET}`;
    }

    // Output: [Model] dir | branch [n] | free (%) [+delta] [AC] session
    const base = `${DIM}[${model}]${RESET} ${BLUE}${dirName}${RESET}`;
    const maxWidth = getTerminalWidth();
    const parts = [base, gitInfo, contextInfo, deltaInfo, acInfo, sessionInfo];
    console.log(fitToWidth(parts, maxWidth));
});

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { maybeRotateStateFile, ROTATION_THRESHOLD, ROTATION_KEEP };
}
