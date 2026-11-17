import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const html = fs.readFileSync('StatsByDate.html', 'utf8');

const match = html.match(
    /function nhlGoalStrength\([^)]*\)\s*\{[\s\S]*?\n\}/
);

assert.ok(match, 'nhlGoalStrength not found');

const classify = vm.runInNewContext(
    '(' + match[0] + ')'
);

let passed = 0;
let failed = 0;

function test(name, goal, isHome, expected) {
    const actual = classify(goal, isHome);

    if (actual === expected) {
        console.log(`PASS ${name}: ${actual}`);
        passed++;
    } else {
        console.log(
            `FAIL ${name}: expected ${expected}, got ${actual}`
        );
        failed++;
    }
}

// Synthetic tests: away and home scoring.
const situations = [
    ['1551', 'EQ',   'EQ'],
    ['1441', 'EQ',   'EQ'],
    ['1331', 'EQ',   'EQ'],
    ['1541', 'PP1',  'SH1'],
    ['1451', 'SH1',  'PP1'],
    ['1531', 'PP2',  'SH2'],
    ['1351', 'SH2',  'PP2'],
    ['1431', 'PP1',  'SH1'],
    ['1341', 'SH1',  'PP1'],
    ['0651', '6on5', 'ENG'],
    ['1560', 'ENG',  '6on5'],
    ['0641', '6on4', 'ENG'],
    ['1460', 'ENG',  '6on4'],
    ['0631', '6on3', 'ENG'],
    ['1360', 'ENG',  '6on3']
];

for (const [code, away, home] of situations) {
    const goal = {
        situationCode: code,
        details: {}
    };

    test(`${code} away`, goal, false, away);
    test(`${code} home`, goal, true, home);
}

// Special situations.
test('Shootout', {
    periodDescriptor: {periodType: 'SO'}
}, true, 'SO');

test('Explicit ENG flag', {
    situationCode: '1551',
    details: {emptyNet: true}
}, false, 'ENG');

test('Missing situationCode', {}, false, '');

test('Invalid situationCode', {
    situationCode: '9999'
}, true, '');

// Real match data.
const games = [
    {
        id: '2026020329',
        expected: [
            'PP1', 'EQ', 'PP1', 'EQ', 'SH1',
            'EQ', 'PP1', 'EQ', 'ENG'
        ]
    },
    {
        id: '2026020332',
        expected: [
            'PP1', 'PP1', 'EQ', 'EQ', 'PP1'
        ]
    }
];

for (const {id, expected} of games) {
    const path =
        `statsByDate/data/raw/games/NHL/${id}/play-by-play.json`;

    const data = JSON.parse(fs.readFileSync(path, 'utf8'));

    const goals = data.plays.filter(
        p => p.typeDescKey === 'goal'
    );

    assert.equal(goals.length, expected.length);

    goals.forEach((goal, i) => {
        const isHome =
            String(goal.details.eventOwnerTeamId) ===
            String(data.homeTeam.id);

        test(
            `${id} P${goal.periodDescriptor.number} ` +
            goal.timeInPeriod,
            goal,
            isHome,
            expected[i]
        );
    });
}

console.log('\n-------------------------');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total:  ${passed + failed}`);

process.exitCode = failed ? 1 : 0;
