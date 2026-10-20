/* SPDX-License-Identifier: GPL-2.0-only
 * ARTIFICIAL NATIVE-C COMPONENT UNIT, NOT A SOLVER OR PHYSICAL QUALIFICATION.
 *
 * Includes the ACTUAL production implementation in this one translation unit,
 * exposing its existing private statics to the unit without changing production
 * accessors. Link the real CalculiX strcmp1.o and include its CalculiX.h.
 *
 * Manufactured residuals, zero coordinates, no elements and no cut bodies are
 * intentional. These tests prove scheduler/projection guard behavior only.
 * Real unchanged mixed-contact and analytic CAD/solver fixtures remain required.
 */
#define _POSIX_C_SOURCE 200809L
#ifndef FREECAD_FORCE_ACCOUNTING_SOURCE
#define FREECAD_FORCE_ACCOUNTING_SOURCE "../../calculix/force-accounting/forceaccounting.c"
#endif
#include FREECAD_FORCE_ACCOUNTING_SOURCE

#define UNIT_MAX_NODES 6
#define UNIT_MAX_ROWS 4
#define UNIT_MAX_TERMS 16
#define UNIT_MT 4

typedef struct {
    ITG nk, nmpc, used, support;
    ITG starts[UNIT_MAX_ROWS], terms[3 * UNIT_MAX_TERMS];
    ITG active[UNIT_MT * UNIT_MAX_NODES];
    double coefficients[UNIT_MAX_TERMS];
    double internal[UNIT_MT * UNIT_MAX_NODES];
    double external[UNIT_MT * UNIT_MAX_NODES];
    double displacement[UNIT_MT * UNIT_MAX_NODES];
    double coordinates[3 * UNIT_MAX_NODES];
    uint64_t ownership[UNIT_MAX_NODES], intersection[UNIT_MAX_NODES];
} UnitFixture;

static void unit_fail(const char* reason)
{
    fprintf(stderr, "ARTIFICIAL_COMPONENT_UNIT_FAILURE: %s\n", reason);
    exit(2);
}

static void begin_fixture(UnitFixture* test, ITG nk, ITG support)
{
    ITG node, dir, active = 1, prescribed = 1;
    memset(test, 0, sizeof(*test));
    test->nk = nk;
    test->support = support;
    for (node = 0; node < nk; node++) {
        for (dir = 1; dir <= 3; dir++) {
            test->active[UNIT_MT * node + dir] = active++;
        }
    }
    for (node = support - 1; node <= support; node++) {
        for (dir = 1; dir <= 3; dir++) {
            test->active[UNIT_MT * node + dir] = -2 * prescribed++;
        }
    }
}

static void row(UnitFixture* test, ITG count, const ITG* nodes, const double* coefficients)
{
    ITG i, term, start;
    if (count < 1 || test->nmpc >= UNIT_MAX_ROWS || test->used + count > UNIT_MAX_TERMS) {
        unit_fail("artificial fixture storage bound");
    }
    start = test->used;
    test->starts[test->nmpc] = start + 1;
    for (i = 0; i < count; i++) {
        term = test->used++;
        test->terms[3 * term] = nodes[i];
        test->terms[3 * term + 1] = 1;
        test->terms[3 * term + 2] = i + 1 < count ? term + 2 : 0;
        test->coefficients[term] = coefficients[i];
    }
    /* Native mapping is -2*row-1. Preserve the first mapping for an explicitly
     * invalid repeated-pivot fixture, which cannot map to two different rows.
     */
    term = UNIT_MT * (nodes[0] - 1) + 1;
    if (test->active[term] >= 0) {
        test->active[term] = -2 * test->nmpc - 1;
    }
    test->nmpc++;
}

static void pair(UnitFixture* test, ITG dependent, ITG independent, double scale)
{
    ITG nodes[2] = {dependent, independent};
    double coefficients[2] = {scale, -scale};
    row(test, 2, nodes, coefficients);
}

static void branch_root(UnitFixture* test, double scale, int duplicate_edge)
{
    ITG nodes[4] = {1, 2, 3, 3};
    double coefficients[4] = {scale, -0.25 * scale, -0.75 * scale, 0};
    if (duplicate_edge) {
        nodes[2] = 2;
        coefficients[1] = -0.125 * scale;
        coefficients[2] = -0.125 * scale;
        coefficients[3] = -0.75 * scale;
    }
    row(test, duplicate_edge ? 4 : 3, nodes, coefficients);
}

static const char* configure(UnitFixture* test, const char* name, double* expected)
{
    if (!strcmp(name, "chain-wrong-order") || !strcmp(name, "chain-forward") ||
        !strcmp(name, "chain-scaled") || !strcmp(name, "chain-dependent-external") ||
        !strcmp(name, "zero-edge-not-cycle")) {
        begin_fixture(test, 4, 3);
        if (!strcmp(name, "chain-forward")) {
            pair(test, 1, 2, 1);
            pair(test, 2, 3, 1);
        } else if (!strcmp(name, "zero-edge-not-cycle")) {
            ITG nodes[3] = {2, 3, 1};
            double coefficients[3] = {1, -1, 0};
            row(test, 3, nodes, coefficients);
            pair(test, 1, 2, 1);
        } else {
            pair(test, 2, 3, !strcmp(name, "chain-scaled") ? -4 : 1);
            pair(test, 1, 2, !strcmp(name, "chain-scaled") ? 0.25 : 1);
        }
        test->internal[UNIT_MT * 0 + 1] = 10;
        test->internal[UNIT_MT * 1 + 1] = 2;
        if (!strcmp(name, "chain-dependent-external")) {
            test->internal[UNIT_MT * 0 + 1] = 15;
            test->external[UNIT_MT * 0 + 1] = 5;
        }
        *expected = 12;
        return NULL;
    }
    if (!strcmp(name, "branch-permuted") || !strcmp(name, "branch-scaled") ||
        !strcmp(name, "duplicate-edge")) {
        begin_fixture(test, 5, 4);
        if (!strcmp(name, "branch-scaled")) {
            pair(test, 2, 4, -4);
            branch_root(test, 0.25, 0);
            pair(test, 3, 4, 8);
        } else {
            pair(test, 3, 4, 1);
            pair(test, 2, 4, 1);
            branch_root(test, 1, !strcmp(name, "duplicate-edge"));
        }
        test->internal[UNIT_MT * 0 + 1] = 8;
        test->internal[UNIT_MT * 1 + 1] = 1;
        test->internal[UNIT_MT * 2 + 1] = 2;
        *expected = 11;
        return NULL;
    }
    begin_fixture(test, 4, 3);
    if (!strcmp(name, "reject-cycle")) {
        pair(test, 1, 2, 1);
        pair(test, 2, 1, 1);
        return "native MPC dependency graph contains a nonzero cycle";
    }
    if (!strcmp(name, "reject-self")) {
        pair(test, 1, 1, 1);
        return "native MPC dependency graph contains a self-reference";
    }
    if (!strcmp(name, "reject-repeated-pivot")) {
        pair(test, 1, 3, 1);
        pair(test, 1, 2, 1);
        return "MPC dependent degrees of freedom are not uniquely active";
    }
    if (!strcmp(name, "reject-linked-list-cycle")) {
        pair(test, 1, 3, 1);
        test->terms[3 * 1 + 2] = 1;
        return "native MPC term lists overlap or contain a cycle";
    }
    if (!strcmp(name, "reject-nonfinite-pivot")) {
        pair(test, 1, 3, 1);
        test->coefficients[0] = NAN;
        return "unsupported MPC dependent coefficient";
    }
    unit_fail("unknown artificial component case");
    return NULL;
}

static void check_order(UnitFixture* test, ITG* order)
{
    ITG i, j, index, node, pivot, positions[UNIT_MAX_ROWS];
    unsigned char seen[UNIT_MAX_ROWS] = {0};
    for (i = 0; i < test->nmpc; i++) {
        if (order[i] < 0 || order[i] >= test->nmpc || seen[order[i]]) {
            unit_fail("validate_mpcs did not return a complete row permutation");
        }
        seen[order[i]] = 1;
        positions[order[i]] = i;
    }
    for (i = 0; i < test->nmpc; i++) {
        index = test->starts[i] - 1;
        while (test->terms[3 * index + 2]) {
            index = test->terms[3 * index + 2] - 1;
            if (!test->coefficients[index]) {
                continue;
            }
            node = test->terms[3 * index];
            for (j = 0; j < test->nmpc; j++) {
                pivot = test->starts[j] - 1;
                if (test->terms[3 * pivot] == node && positions[i] >= positions[j]) {
                    unit_fail("returned order violates an independently checked graph edge");
                }
            }
        }
    }
}

static void verify_output(const char* request, double expected, double* values)
{
    char path[4096], line[1024], kind[81], name[81];
    FILE* output;
    int supports = 0, end = 0;
    if (snprintf(path, sizeof(path), "%s.out", request) >= (int)sizeof(path)) {
        unit_fail("unit output path exceeds bound");
    }
    output = fopen(path, "r");
    if (!output || !fgets(line, sizeof(line), output) || strcmp(line, "CCX_FORCE_ACCOUNTING_V2\n")) {
        unit_fail("missing actual fa_emit V2 envelope");
    }
    while (fgets(line, sizeof(line), output)) {
        if (!strncmp(line, "SUPPORT ", 8)) {
            if (sscanf(line, "%80s %80s %lf %lf %lf %lf %lf %lf", kind, name,
                       &values[0], &values[1], &values[2], &values[3], &values[4], &values[5]) != 8 ||
                strcmp(name, "ArtificialSupport")) {
                unit_fail("unexpected actual fa_emit support row");
            }
            supports++;
        }
        if (!strcmp(line, "END\n")) {
            end++;
        }
    }
    fclose(output);
    /* All artificial references/scales are integers or powers of two and hence
     * exactly representable. Exact comparison is a component arithmetic check,
     * NOT a new physical acceptance tolerance or an engineering zero-error rule.
     */
    if (supports != 1 || end != 1 || values[0] != expected || values[1] || values[2] ||
        values[3] || values[4] || values[5]) {
        unit_fail("actual fa_emit support differs from fixed algebra reference");
    }
}

int main(int argc, char** argv)
{
    UnitFixture test;
    ITG* order;
    ITG i;
    const char* rejection;
    double expected = 0, values[6] = {0};
    if (argc != 3) {
        fprintf(stderr, "usage: NativeMpcComponentUnit CASE PRIVATE_OUTPUT_REQUEST_PREFIX\n");
        return 2;
    }
    rejection = configure(&test, argv[1], &expected);
    memset(&fa, 0, sizeof(fa));
    fa.active = 1;
    fa.version = 2;
    fa.nk = test.nk;
    fa.mpc_capacity = test.used;
    fa.co = test.coordinates;
    fa.original_co = test.coordinates;
    fa.node_union = test.ownership;
    fa.node_intersection = test.intersection;
    fa.ns = 1;
    strcpy(fa.supports[0].name, "ArtificialSupport");
    fa.supports[0].ref = test.support;
    fa.supports[0].rot = test.support + 1;
    if (setenv("CCX_FORCE_ACCOUNTING_REQUEST", argv[2], 1)) {
        unit_fail("cannot set unit-owned output path");
    }
    if (rejection) {
        printf("EXPECTED_ARTIFICIAL_COMPONENT_REFUSAL: %s\n", rejection);
        fflush(stdout);
    }
    order = validate_mpcs(test.nk, UNIT_MT, test.active, test.nmpc,
                          test.starts, test.terms, test.coefficients);
    if (rejection) {
        free(order);
        unit_fail("invalid artificial component fixture was unexpectedly accepted");
    }
    check_order(&test, order);
    fa_emit(test.internal, test.external, test.nk, UNIT_MT, test.active,
            test.nmpc, test.starts, test.terms, test.coefficients,
            test.displacement, 1, 1, 1.0);
    verify_output(argv[2], expected, values);
    printf("{\"scope\":\"ARTIFICIAL_NATIVE_C_COMPONENT_UNIT_NOT_PHYSICAL_QUALIFICATION\","
           "\"case\":\"%s\",\"validate_mpcs_order\":[", argv[1]);
    for (i = 0; i < test.nmpc; i++) {
        printf("%s%d", i ? "," : "", (int)order[i]);
    }
    printf("],\"support\":[%.17g,0,0,0,0,0],\"expected_support_x\":%.17g,\"passed\":true}\n",
           values[0], expected);
    free(order);
    return 0;
}
