#!/usr/bin/env node
/**
 * scripts/find_tdz_reads.mjs
 * ==========================
 * Find block-scoped variables read before their declaration during render.
 *
 * The Watchlist page shipped this and crashed for every user with a non-empty
 * watchlist:
 *
 *     const enrichedItems = items.map((item) => ({ ...item,
 *       history: tickHistory[item.symbol] ?? item.history }));   // line 168
 *     ...
 *     const [tickHistory, setTickHistory] = useState({});        // line 192
 *
 * Reading a `const` above its declaration is a temporal dead zone violation:
 * `ReferenceError: Cannot access 'tickHistory' before initialization`. Minified,
 * that reads `Cannot access 'N' before initialization`.
 *
 * Nothing in this repo's toolchain catches it:
 *
 *  * `tsc` raises TS2448 only for a *direct* reference in the same scope. The
 *    read above is inside a `.map()` callback, and TypeScript will not assume
 *    when a callback runs — so `npm run typecheck` and `npm run build` pass.
 *  * There is no ESLint config in this project, so `no-use-before-define`
 *    has never run against it.
 *
 * So this is the check. It walks the TypeScript AST and reports a reference to
 * a `const`/`let` that appears earlier in the source than the declaration, and
 * that is reached *synchronously during render*:
 *
 *  * a direct reference in the function body, or
 *  * a reference inside a callback passed to an eagerly-invoked array method
 *    (`map`, `filter`, `forEach`, `reduce`, `find`, `some`, `every`, `sort`,
 *    `flatMap`), which React runs as part of the render pass.
 *
 * Event handlers (`onClick={() => setX(y)}`) and effect bodies are deliberately
 * NOT flagged: they run after the whole body has evaluated, so an early
 * reference in one is legal and extremely common.
 *
 * Usage:  node scripts/find_tdz_reads.mjs [rootDir]
 * Exit:   0 clean, 1 findings.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import ts from 'typescript';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = join(HERE, '..', 'src');

/** Array methods React evaluates during the render pass. */
const EAGER_METHODS = new Set([
  'map', 'filter', 'forEach', 'reduce', 'reduceRight',
  'find', 'findIndex', 'findLast', 'some', 'every', 'sort', 'flatMap',
]);

function walkFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'dist') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walkFiles(full, out);
    else if (['.ts', '.tsx'].includes(extname(name))) out.push(full);
  }
  return out;
}

/**
 * Collect `const`/`let` names declared directly in a function body block,
 * mapped to the position of their declaration.
 */
function blockScopedDeclarations(body) {
  const declared = new Map();
  if (!body || !ts.isBlock(body)) return declared;

  for (const stmt of body.statements) {
    if (!ts.isVariableStatement(stmt)) continue;
    const flags = stmt.declarationList.flags;
    const blockScoped = (flags & ts.NodeFlags.Let) || (flags & ts.NodeFlags.Const);
    if (!blockScoped) continue;

    for (const decl of stmt.declarationList.declarations) {
      collectBindingNames(decl.name, decl.getStart(), declared);
    }
  }
  return declared;
}

function collectBindingNames(name, pos, out) {
  if (ts.isIdentifier(name)) {
    out.set(name.text, pos);
  } else if (ts.isArrayBindingPattern(name) || ts.isObjectBindingPattern(name)) {
    for (const el of name.elements) {
      if (ts.isBindingElement(el)) collectBindingNames(el.name, pos, out);
    }
  }
}

/**
 * True when `node` appears in a type position (`as { msg?: string }`,
 * `Record<string, Foo>`, an interface member…). Type syntax is erased at
 * compile time and never evaluates, so a name there is not a runtime read.
 * Without this, every `const d = raw as { msg?: string }` in the codebase
 * looks like a read of a variable that happens to share the member's name.
 */
function isInTypePosition(node) {
  let current = node.parent;
  while (current) {
    if (ts.isTypeNode(current) || ts.isTypeAliasDeclaration(current) || ts.isInterfaceDeclaration(current)) {
      return true;
    }
    current = current.parent;
  }
  return false;
}

/**
 * True when an inner scope between `node` and the function body redeclares
 * `name` — the reference then resolves to that inner binding, not the outer
 * one, and there is no dead zone. `CryptoCheckout.parseRates` declares `const
 * get` twice in two sibling blocks; without this the first one's uses look
 * like early reads of the second.
 */
function isShadowedBefore(node, name, functionBody) {
  let current = node.parent;
  while (current && current !== functionBody) {
    if (ts.isBlock(current) || ts.isCaseClause(current) || ts.isSourceFile(current)) {
      for (const stmt of current.statements ?? []) {
        if (!ts.isVariableStatement(stmt)) continue;
        const names = new Map();
        for (const decl of stmt.declarationList.declarations) {
          collectBindingNames(decl.name, decl.getStart(), names);
        }
        if (names.has(name)) return true;
      }
    }
    // Parameters and nested function names shadow too.
    if (
      ts.isFunctionDeclaration(current) ||
      ts.isFunctionExpression(current) ||
      ts.isArrowFunction(current) ||
      ts.isMethodDeclaration(current)
    ) {
      for (const param of current.parameters ?? []) {
        const names = new Map();
        collectBindingNames(param.name, param.getStart(), names);
        if (names.has(name)) return true;
      }
    }
    current = current.parent;
  }
  return false;
}

/** True when `node` sits inside a callback that render evaluates eagerly. */
function isRenderReachable(node, functionBody) {
  let current = node.parent;
  while (current && current !== functionBody) {
    if (
      ts.isFunctionDeclaration(current) ||
      ts.isFunctionExpression(current) ||
      ts.isArrowFunction(current) ||
      ts.isMethodDeclaration(current)
    ) {
      // A nested function. It is only render-reachable if it is the argument
      // to an eagerly-invoked array method.
      const call = current.parent;
      if (
        call &&
        ts.isCallExpression(call) &&
        ts.isPropertyAccessExpression(call.expression) &&
        EAGER_METHODS.has(call.expression.name.text)
      ) {
        current = call;
        continue;
      }
      return false; // handler, effect body, memo callback invoked later
    }
    current = current.parent;
  }
  return true;
}

function checkFunctionBody(body, sourceFile, findings, filePath) {
  const declared = blockScopedDeclarations(body);
  if (declared.size === 0) return;

  const visit = (node) => {
    if (ts.isIdentifier(node)) {
      const declPos = declared.get(node.text);
      const isDeclarationSite = declPos !== undefined && node.getStart() >= declPos;

      if (declPos !== undefined && !isDeclarationSite) {
        // A property name (`obj.tickHistory`) or a key in `{ tickHistory: 1 }`
        // is not a reference to the binding.
        const parent = node.parent;
        const isPropertyName =
          (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
          (ts.isPropertyAssignment(parent) && parent.name === node);

        if (
          !isPropertyName &&
          !isInTypePosition(node) &&
          !isShadowedBefore(node, node.text, body) &&
          isRenderReachable(node, body)
        ) {
          const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
          const { line: declLine } = sourceFile.getLineAndCharacterOfPosition(declPos);
          findings.push({ file: filePath, name: node.text, readLine: line + 1, declLine: declLine + 1 });
        }
      }
    }
    ts.forEachChild(node, visit);
  };

  ts.forEachChild(body, visit);
}

export function scan(root = DEFAULT_ROOT) {
  const findings = [];

  for (const file of walkFiles(root)) {
    const text = readFileSync(file, 'utf-8');
    const sourceFile = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    const visit = (node) => {
      if (
        ts.isFunctionDeclaration(node) ||
        ts.isFunctionExpression(node) ||
        ts.isArrowFunction(node) ||
        ts.isMethodDeclaration(node)
      ) {
        checkFunctionBody(node.body, sourceFile, findings, file);
      }
      ts.forEachChild(node, visit);
    };
    ts.forEachChild(sourceFile, visit);
  }

  return findings;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const root = process.argv[2] ? process.argv[2] : DEFAULT_ROOT;
  const findings = scan(root);

  if (findings.length === 0) {
    console.log('No render-time temporal dead zone reads found.');
    process.exit(0);
  }

  console.error(`${findings.length} render-time temporal dead zone read(s):\n`);
  for (const f of findings) {
    console.error(
      `  ${relative(process.cwd(), f.file)}:${f.readLine}  reads '${f.name}', declared at line ${f.declLine}`,
    );
  }
  console.error('\nEach one throws "Cannot access \'<name>\' before initialization" at render.');
  process.exit(1);
}
