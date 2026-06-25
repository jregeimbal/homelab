"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.opencodeAdapter = void 0;
const schema_1 = require("../schema");
const json_1 = require("../json");
const common_1 = require("./common");
const MODEL_CATALOG = {
    'opencode/big-pickle': { rank: 1 },
    'opencode/glm-4.7-free': { rank: 1 },
    'opencode/gpt-5-nano': { rank: 1 },
    'opencode/grok-code': { rank: 1 },
    'opencode/minimax-m2.1-free': { rank: 1 },
    'google/gemini-1.5-flash': { rank: 1 },
    'google/gemini-1.5-flash-8b': { rank: 1 },
    'google/gemini-1.5-pro': { rank: 1 },
    'google/gemini-2.0-flash': { rank: 1 },
    'google/gemini-2.0-flash-lite': { rank: 1 },
    'google/gemini-2.5-flash': { rank: 1 },
    'google/gemini-2.5-flash-image': { rank: 1 },
    'google/gemini-2.5-flash-image-preview': { rank: 1 },
    'google/gemini-2.5-flash-lite': { rank: 1 },
    'google/gemini-2.5-flash-lite-preview-06-17': { rank: 1 },
    'google/gemini-2.5-flash-lite-preview-09-2025': { rank: 1 },
    'google/gemini-2.5-flash-preview-04-17': { rank: 1 },
    'google/gemini-2.5-flash-preview-05-20': { rank: 1 },
    'google/gemini-2.5-flash-preview-09-2025': { rank: 1 },
    'google/gemini-2.5-flash-preview-tts': { rank: 1 },
    'google/gemini-2.5-pro': { rank: 1 },
    'google/gemini-2.5-pro-preview-05-06': { rank: 1 },
    'google/gemini-2.5-pro-preview-06-05': { rank: 1 },
    'google/gemini-2.5-pro-preview-tts': { rank: 1 },
    'google/gemini-3-flash-preview': { rank: 1 },
    'google/gemini-3-pro-preview': { rank: 1 },
    'google/gemini-embedding-001': { rank: 1 },
    'google/gemini-flash-latest': { rank: 1 },
    'google/gemini-flash-lite-latest': { rank: 1 },
    'google/gemini-live-2.5-flash': { rank: 1 },
    'google/gemini-live-2.5-flash-preview-native-audio': { rank: 1 },
    'openai/gpt-5.1-codex-max': { rank: 1 },
    'openai/gpt-5.1-codex-mini': { rank: 1 },
    'openai/gpt-5.2': { rank: 1 },
    'openai/gpt-5.2-codex': { rank: 1 },
};
const LEVEL_MAPPING = {
    level1: { rank: 1, model: null, reasoningEffort: 'low' },
    level2: { rank: 2, model: null, reasoningEffort: 'medium' },
    level3: { rank: 3, model: null, reasoningEffort: 'high' },
};
function detectCliFeatures(helpText) {
    const help = helpText ?? '';
    const unknown = !help;
    return {
        provider: 'opencode',
        supportsJson: unknown ? true : /--format\b/.test(help),
        supportsModel: unknown ? true : /--model\b/.test(help),
        supportsVariant: unknown ? true : /--variant\b/.test(help),
        supportsCwd: unknown ? false : /--cwd\b/.test(help),
        supportsDir: unknown ? false : /--dir\b/.test(help),
        supportsAutoApprove: false,
        unknown,
    };
}
function addOpencodeOptionalArgs(args, options) {
    const features = (0, common_1.optionFeatures)(options);
    if ((options.outputFormat === 'stream-json' || options.outputFormat === 'json') &&
        features.supportsJson) {
        args.push('--format', 'json');
    }
    if (options.modelSpec?.model) {
        args.push('--model', options.modelSpec.model);
    }
    if (options.modelSpec?.reasoningEffort && features.supportsVariant) {
        args.push('--variant', options.modelSpec.reasoningEffort);
    }
    if (options.cwd && features.supportsCwd) {
        args.push('--cwd', options.cwd);
    } else if (options.cwd && features.supportsDir) {
        args.push('--dir', options.cwd);
    }
}
function collectOpencodeWarnings(options) {
    const features = (0, common_1.optionFeatures)(options);
    const warnings = (0, common_1.unsupportedSessionControlWarnings)('opencode', options);
    if (options.modelSpec?.reasoningEffort && features.supportsVariant === false) {
        warnings.push((0, common_1.warning)('opencode', 'opencode-variant', 'Opencode CLI does not support --variant; skipping reasoningEffort.'));
    }
    return warnings;
}
function buildCommand(context, options = {}) {
    const finalContext = options.jsonSchema
        ? (0, schema_1.appendJsonSchemaPrompt)(context, options.jsonSchema)
        : context;
    const args = ['run'];
    addOpencodeOptionalArgs(args, options);
    args.push(finalContext);
    return (0, common_1.commandSpec)({
        binary: 'opencode',
        args,
        env: {},
        ...(options.cwd === undefined ? {} : { cwd: options.cwd }),
        warnings: collectOpencodeWarnings(options),
    });
}
function parseToolPart(part) {
    const state = (0, json_1.getRecord)(part, 'state') ?? {};
    const status = (0, json_1.getString)(state, 'status');
    if (status === 'pending' || status === 'running') {
        return {
            type: 'tool_call',
            toolName: (0, json_1.getOptionalString)(part, 'tool'),
            toolId: (0, json_1.getOptionalString)(part, 'callID'),
            input: state.input ?? {},
        };
    }
    if (status === 'completed') {
        return {
            type: 'tool_result',
            toolId: (0, json_1.getOptionalString)(part, 'callID'),
            content: state.output || '',
            isError: false,
        };
    }
    if (status === 'error') {
        return {
            type: 'tool_result',
            toolId: (0, json_1.getOptionalString)(part, 'callID'),
            content: state.error || '',
            isError: true,
        };
    }
    return null;
}
function parseStepFinish(part) {
    const tokens = (0, json_1.getRecord)(part, 'tokens') ?? {};
    return {
        type: 'result',
        success: true,
        inputTokens: (0, json_1.getNumber)(tokens, 'input') ?? 0,
        outputTokens: (0, json_1.getNumber)(tokens, 'output') ?? 0,
    };
}
function parsePart(part) {
    if (!(0, json_1.isRecord)(part))
        return null;
    if ((0, json_1.getString)(part, 'type') === 'text') {
        const text = (0, json_1.getString)(part, 'text');
        if (text)
            return { type: 'text', text };
    }
    if ((0, json_1.getString)(part, 'type') === 'reasoning') {
        const text = (0, json_1.getString)(part, 'text');
        if (text)
            return { type: 'thinking', text };
    }
    if ((0, json_1.getString)(part, 'type') === 'tool') {
        return parseToolPart(part);
    }
    if ((0, json_1.getString)(part, 'type') === 'step-finish') {
        return parseStepFinish(part);
    }
    return null;
}
function parseErrorEvent(event) {
    const error = (0, json_1.getRecord)(event, 'error') ?? {};
    const data = (0, json_1.getRecord)(error, 'data');
    return {
        type: 'result',
        success: false,
        error: (data ? (0, json_1.getString)(data, 'message') : null) ??
            (0, json_1.getString)(error, 'message') ??
            (0, json_1.getString)(error, 'name') ??
            'Unknown error',
    };
}
function parseEvent(line) {
    const event = (0, json_1.tryParseJson)(line);
    if (!(0, json_1.isRecord)(event))
        return null;
    const type = (0, json_1.getString)(event, 'type');
    if (type === 'error')
        return parseErrorEvent(event);
    if (type === 'text' || type === 'step_start' || type === 'step_finish') {
        return parsePart(event.part ?? event);
    }
    if (type === 'message.part.updated') {
        const properties = (0, json_1.getRecord)(event, 'properties');
        return parsePart(properties?.part);
    }
    return null;
}
function resolveModelSpec(level, overrides) {
    return (0, common_1.resolveModelSpecWithConfig)({
        mapping: LEVEL_MAPPING,
        defaultLevel: 'level2',
        level,
        overrides,
        validateModelId,
    });
}
function validateModelId(modelId) {
    return (0, common_1.validateModelIdFromCatalog)('opencode', MODEL_CATALOG, modelId);
}
function classifyError(error) {
    return (0, common_1.classifyBaseProviderError)(error, [], []);
}
exports.opencodeAdapter = {
    id: 'opencode',
    displayName: 'Opencode',
    binary: 'opencode',
    adapterVersion: '1',
    credentialEnvKeys: [
        'OPENCODE_API_KEY',
        'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY',
        'GEMINI_API_KEY',
        'GOOGLE_API_KEY',
    ],
    modelCatalog: MODEL_CATALOG,
    levelMapping: LEVEL_MAPPING,
    defaultLevel: 'level2',
    defaultMaxLevel: 'level3',
    defaultMinLevel: 'level1',
    detectCliFeatures,
    buildCommand,
    parseEvent,
    createParserState: () => (0, common_1.createParserState)('opencode'),
    resolveModelSpec,
    validateModelId,
    classifyError,
};
//# sourceMappingURL=opencode.js.map