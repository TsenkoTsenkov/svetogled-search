#!/usr/bin/env node
/**
 * Tests for the vim motions of режим на редакция.
 *
 * The motion layer inside redaction.html is deliberately kept free of the
 * DOM: given a paragraph and an offset it answers with another offset, and
 * nothing else. That makes it testable without a browser — this file lifts
 * the block out of the page and runs it.
 *
 * Covered here:
 *     1. Word motions over Bulgarian text (w b e ge, and their big cousins)
 *     2. f F t T, including the "already there" cases
 *     3. Sentences — the rule ( ) and is/as follow
 *     4. Text objects: iw aw is as ip and the quotes, „…“ included
 *     5. Search with vim's smartcase
 *
 *     node test_vim_motions.js
 */

"use strict";

const fs = require("fs");
const path = require("path");

const PAGE = path.join(__dirname, "redaction.html");
const OPEN = "// ── vim: pure text motions";
const CLOSE = "// ── end vim pure motions";

function loadMotions() {
    const html = fs.readFileSync(PAGE, "utf8");
    const from = html.indexOf(OPEN);
    const to = html.indexOf(CLOSE);
    if (from < 0 || to < 0)
        throw new Error(
            "redaction.html no longer marks the pure motion block — " +
                "look for " + OPEN,
        );
    const source = html.slice(from, to);
    if (/document\.|window\.|getElementById/.test(source))
        throw new Error("the motion block reached for the DOM; it must stay pure");
    return new Function(source + "\n; return VimText;")();
}

const V = loadMotions();

// A паragraph of the shape the editor really hands over: one line, no
// newlines, Bulgarian text with its own punctuation.
const P = "Днес ще говорим за иконата и за нейното богословие.";
const at = (w) => P.indexOf(w);

let passed = 0;
let failed = 0;

function check(name, got, want) {
    const same = JSON.stringify(got) === JSON.stringify(want);
    if (same) {
        passed++;
        console.log("  PASS  " + name);
    } else {
        failed++;
        console.log("  FAIL  " + name);
        console.log("        got  " + JSON.stringify(got));
        console.log("        want " + JSON.stringify(want));
    }
}

/** A text object, rendered as the string it covers. */
function obj(text, pos, key, inner) {
    const o = V.textObject(text, pos, key, inner);
    return o === null ? null : text.slice(o.start, o.end);
}

// ── Word motions ─────────────────────────────────────────────────────

check("w from the first word", V.wordFwd(P, 0, false), at("ще"));
check("w from mid-word", V.wordFwd(P, 2, false), at("ще"));
check("w stops on the full stop — punctuation is a word",
    V.wordFwd(P, at("богословие"), false), P.length - 1);
check("w from the full stop reaches the end", V.wordFwd(P, P.length - 1, false), P.length);
check("W treats punctuation as part of the word",
    V.wordFwd("виж (скоба) там", 0, true), 4);
check("w stops at punctuation, W does not",
    [V.wordFwd("виж (скоба) там", 0, false), V.wordFwd("виж (скоба) там", 0, true)],
    [4, 4]);
check("w off punctuation", V.wordFwd("а, б", 1, false), 3);
check("b back a word", V.wordBack(P, at("иконата"), false), at("за иконата"));
check("b from the very start stays", V.wordBack(P, 0, false), 0);
check("e to the end of this word", V.wordEnd(P, 0, false), 3);
check("e from a word end goes to the next", V.wordEnd(P, 3, false), at("ще") + 1);
check("ge back to the previous word end", V.wordEndBack(P, at("говорим")), at("ще") + 1);
check("word motions на кирилица treat letters as letters",
    V.klass("щ", false), 2);
check("digits are word characters", V.klass("7", false), 2);
check("punctuation is its own class", V.klass(",", false), 1);
check("a space is blank", V.klass(" ", false), 0);

// ── Lines ────────────────────────────────────────────────────────────

const TWO = "първи ред\nвтори ред";
check("lineStart on the second line", V.lineStart(TWO, 12), 10);
check("lineStart at zero", V.lineStart(TWO, 0), 0);
check("lineEnd on the first line", V.lineEnd(TWO, 2), 9);
check("firstNonBlank skips the indent", V.firstNonBlank("   дума", 5), 3);

// ── f F t T ──────────────────────────────────────────────────────────

check("f finds the letter", V.findChar(P, 0, "г", false, false, 1), at("говорим"));
check("f twice finds the second one", V.findChar(P, 0, "г", false, false, 2), at("богословие") + 2);
check("f fails when the letter is not ahead", V.findChar(P, 0, "щ", true, false, 1), -1);
check("t stops one short", V.findChar(P, 0, "г", false, true, 1), at("говорим") - 1);
// Standing right before the letter, t moves to the *next* one instead of
// refusing — vim's `cpo-=;` behaviour, so repeating never gets stuck.
check("t from just before the letter moves on",
    V.findChar(P, at("говорим") - 1, "г", false, true, 1),
    P.indexOf("г", at("говорим") + 1) - 1);
check("F searches back", V.findChar(P, P.length - 1, "и", true, false, 1), P.lastIndexOf("и"));
check("T stops one short going back",
    V.findChar(P, P.length - 1, "и", true, true, 1), P.lastIndexOf("и") + 1);
check("f does not cross a line", V.findChar(TWO, 0, "т", false, false, 1), -1);

// ── Brackets ─────────────────────────────────────────────────────────

check("% forward", V.matchPair("а (б в) г", 2), 6);
check("% back", V.matchPair("а (б в) г", 6), 2);
check("% counts nesting", V.matchPair("(а (б) в)", 0), 8);
check("% jumps to the bracket ahead", V.matchPair("а (б) в", 0), 4);
check("% with no bracket", V.matchPair("няма скоби", 0), -1);

// ── Sentences ────────────────────────────────────────────────────────

const S = "Първо изречение. Второ изречение! Трето? И четвърто.";
check("sentence starts", V.sentenceStarts(S), [0, 17, 34, 41]);
check(") to the next sentence", V.sentenceFwd(S, 0), 17);
check(") from inside a sentence", V.sentenceFwd(S, 20), 34);
check("( back to this sentence's start", V.sentenceBack(S, 20), 17);
check("a closing quote does not end the sentence early",
    V.sentenceStarts('Той каза „да“. После си тръгна.'), [0, 15]);
check("an ellipsis ends a sentence too",
    V.sentenceStarts("Чакай… После дойде."), [0, 7]);

// ── Text objects ─────────────────────────────────────────────────────

check("iw on a word", obj(P, at("иконата") + 2, "w", true), "иконата");
check("aw takes the space after", obj(P, at("иконата") + 2, "w", false), "иконата ");
check("iw on a space is the run of spaces", obj("а  б", 1, "w", true), "  ");
check("iW spans the punctuation", obj("виж (скоба) там", 6, "W", true), "(скоба)");
check("is is the whole sentence", obj(S, 20, "s", true), "Второ изречение!");
check("as keeps the space after it", obj(S, 20, "s", false), "Второ изречение! ");
check("ip is the paragraph", obj(P, 5, "p", true), P);
check("i\" between plain quotes", obj('той каза "да" вчера', 11, '"', true), "да");
check("a\" takes the quotes too", obj('той каза "да" вчера', 11, '"', false), '"да"');
check("i\" falls back to „…“", obj("той каза „нещо важно“ вчера", 12, '"', true), "нещо важно");
check("i( inside brackets", obj("а (б в) г", 4, "(", true), "б в");
check("a( with the brackets", obj("а (б в) г", 4, "(", false), "(б в)");
check("ib is i(", obj("а (б в) г", 4, "b", true), "б в");
check("i( from the closing bracket", obj("а (б в) г", 6, "(", true), "б в");
check("i( with nothing around", obj("няма скоби", 3, "(", true), null);

// ── Search ───────────────────────────────────────────────────────────

check("plain search", V.searchIn(P, "иконата", 0, false), at("иконата"));
check("search from an offset", V.searchIn(P, "за", at("за иконата") + 1, false), at("за нейното"));
check("backward search", V.searchIn(P, "за", P.length, true), at("за нейното"));
check("smartcase: lower case matches anything", V.searchIn(P, "днес", 0, false), 0);
check("smartcase: a capital is meant", V.searchIn(P, "Иконата", 0, false), -1);
check("smartcase flag", [V.ignoresCase("икона"), V.ignoresCase("Икона")], [true, false]);
check("a missing word is not found", V.searchIn(P, "няма", 0, false), -1);

// ── * and case ───────────────────────────────────────────────────────

check("the word under the cursor", V.wordAt(P, at("иконата") + 3), "иконата");
check("the word after the cursor when on a space", V.wordAt(P, at("иконата") - 1), "иконата");
check("~ swaps case", V.swapCase("Абв ГД"), "аБВ гд");

console.log("\n" + "=".repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log("=".repeat(50));
process.exit(failed === 0 ? 0 : 1);
