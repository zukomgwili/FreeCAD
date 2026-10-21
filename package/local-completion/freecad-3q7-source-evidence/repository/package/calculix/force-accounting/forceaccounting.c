/* SPDX-License-Identifier: GPL-2.0-only
 * Opt-in native static force accounting. Standard RF/SOF/SOM/CF are unchanged.
 * No stress recovery or reconstructed body loads are used here.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "CalculiX.h"
#include <stdint.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
_Static_assert(sizeof(ITG) == sizeof(int), "Force accounting requires a 32-bit integer solver");
double* fa_nodal_loads = NULL;
ITG FORTRAN(fa_collect_loads, ())
{
    return fa_nodal_loads != NULL;
}

#define FA_MAX 64
#define FA_DEFAULT_DECLARATIONS 65536
#define FA_BUDGET_ENV "CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS"
/* Upstream 2.23 stores/addresses labels using native 20*nmpc+1 strides. */
#define FA_MAX_MPC_ROWS ((INT_MAX - 1) / 20)
typedef struct
{
    ITG key[3], element;
} Face;
typedef struct
{
    char name[81];
    ITG ref, rot;
} Support;
typedef struct
{
    char name[81];
    ITG count, *nodes, *directions;
} SPCSupport;
typedef struct
{
    char name[81];
    ITG ref, rot;
    int used;
} Port;
typedef struct
{
    ITG node, rot;
    double axis[3];
    int used;
} Angle;
typedef struct
{
    ITG element, nodes[2];
    int used;
} Spring;
typedef struct
{
    char name[81];
    ITG *elements, *cut, ne, nn;
} Body;
static struct
{
    int active, version, ns, nss, nb, np, na, nsp;
    ITG nk, ne, nfaces, mpc_capacity, budget, declarations;
    size_t owner_words, supports_capacity, spc_capacity, ports_capacity;
    size_t angles_capacity, springs_capacity, bodies_capacity;
    double *co, *original_co, *loads, *contacts;
    ITG *ipkon, *kon;
    char* lakon;
    uint64_t *owners, *node_union, *node_intersection, *contact_owners;
    Face* faces;
    unsigned char* structural_nodes;
    Support* supports;
    SPCSupport* spc_supports;
    Port* ports;
    Angle* angles;
    Spring* springs;
    Body* bodies;
    double* points;
} fa;
/* The main driver decascades before fa_prepare. V3 keeps the original
 * equations separately so a declared angular auxiliary is proved against
 * its actual input equation, not guessed from dummy-node coordinates.
 */
static struct
{
    int captured;
    ITG nk, nmpc, capacity;
    ITG *ipompc, *nodempc;
    double* coef;
    char* labels;
} original_mpcs;

static void fail(const char* message)
{
    fprintf(stderr, "*ERROR CCX force accounting V%d: %s\n", fa.version ? fa.version : 1, message);
    exit(201);
}
static void* allocate(size_t count, size_t size)
{
    if (size && count > SIZE_MAX / size) {
        fail("allocation size overflow");
    }
    void* p = calloc(count ? count : 1, size);
    if (!p) {
        fail("allocation failed");
    }
    return p;
}
static size_t product(size_t left, size_t right)
{
    if (right && left > SIZE_MAX / right) {
        fail("allocation dimension overflow");
    }
    return left * right;
}
static ITG declaration_budget(void)
{
    const char* text = getenv(FA_BUDGET_ENV);
    const char* cursor;
    unsigned long value = 0;
    if (!text) {
        return FA_DEFAULT_DECLARATIONS;
    }
    if (*text < '1' || *text > '9') {
        fail("CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS requires a canonical integer in 1..2147483647");
    }
    for (cursor = text; *cursor; cursor++) {
        if (*cursor < '0' || *cursor > '9' ||
            value > ((unsigned long)INT_MAX - (unsigned long)(*cursor - '0')) / 10) {
            fail("CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS requires a canonical integer in 1..2147483647");
        }
        value = 10 * value + (unsigned long)(*cursor - '0');
    }
    return (ITG)value;
}
int fa_capacity_query(void)
{
    ITG budget;
    fa.version = 3;
    budget = declaration_budget();
    printf("{\"schema\":\"CCX_FORCE_ACCOUNTING_CAPACITY_V1\","
           "\"request_schema\":\"CCX_FORCE_ACCOUNTING_V3\",\"allocation\":\"dynamic\","
           "\"counting_policy\":\"top-level-declarations-v1\",\"total_records\":%d,"
           "\"limits\":{\"supports\":%d,\"bodies\":%d,\"ports\":%d,\"angles\":%d,\"springs\":%d}}\n",
           budget, budget, budget, budget, budget, budget);
    return 0;
}
static void admit_declaration(const char* category, long long required)
{
    if (fa.version != 3) {
        return;
    }
    if (fa.declarations >= fa.budget) {
        fprintf(stderr, "*ERROR CCX force accounting V3: declaration capacity exceeded: "
                "%s required %lld; total required %lld; configured total %d\n",
                category, required, (long long)fa.declarations + 1, fa.budget);
        exit(201);
    }
    fa.declarations++;
}
static void* reserve_storage(void* data, size_t* capacity, size_t size, ITG count)
{
    size_t required = (size_t)count + 1, grown, bytes, previous;
    void* replacement;
    if (required > *capacity) {
        grown = *capacity ? product(*capacity, 2) : 8;
        if (grown < required) {
            grown = required;
        }
        if (grown > (size_t)(fa.version == 3 ? fa.budget : FA_MAX)) {
            grown = (size_t)(fa.version == 3 ? fa.budget : FA_MAX);
        }
        if (grown < required) {
            fail("declaration storage capacity differs from admission");
        }
        bytes = product(grown, size);
        previous = product(*capacity, size);
        replacement = realloc(data, bytes);
        if (!replacement) {
            fail("declaration allocation failed");
        }
        memset((char*)replacement + previous, 0, bytes - previous);
        data = replacement;
        *capacity = grown;
    }
    return data;
}
/* Every row contains the same number of words. A body index chooses its word
 * and bit explicitly, so body 64 cannot alias body 0 or invoke a wide shift.
 * Legacy requests retain exactly one word and their original 64-body limit.
 */
static uint64_t* owner_row(uint64_t* matrix, size_t row)
{
    return matrix + product(row, fa.owner_words);
}
static int owner_has(uint64_t* matrix, size_t row, ITG body)
{
    return (owner_row(matrix, row)[(size_t)body / 64] & (UINT64_C(1) << (body % 64))) != 0;
}
static int owner_any(uint64_t* matrix, size_t row)
{
    size_t word;
    uint64_t* entry = owner_row(matrix, row);
    for (word = 0; word < fa.owner_words; word++) {
        if (entry[word]) {
            return 1;
        }
    }
    return 0;
}
static void owner_add(uint64_t* matrix, size_t row, ITG body)
{
    owner_row(matrix, row)[(size_t)body / 64] |= UINT64_C(1) << (body % 64);
}
void fa_capture_mpcs(
    ITG nk,
    ITG nmpc,
    ITG* ipompc,
    ITG* nodempc,
    double* coef,
    char* labels,
    ITG capacity
)
{
    const char* path = getenv("CCX_FORCE_ACCOUNTING_REQUEST");
    char schema[81];
    FILE* input;
    if (!path || !(input = fopen(path, "r"))) {
        return;
    }
    if (fscanf(input, "%80s", schema) != 1 || strcmp(schema, "CCX_FORCE_ACCOUNTING_V3")) {
        fclose(input);
        return;
    }
    fclose(input);
    fa.version = 3;
    (void)declaration_budget();
    if (original_mpcs.captured || nk < 1 || nmpc < 0 || nmpc > FA_MAX_MPC_ROWS || capacity < 0 ||
        nmpc > capacity || capacity > INT_MAX / 3) {
        fail("invalid or repeated original MPC capture");
    }
    original_mpcs.captured = 1;
    original_mpcs.nk = nk;
    original_mpcs.nmpc = nmpc;
    original_mpcs.capacity = capacity;
    original_mpcs.ipompc = allocate(nmpc, sizeof(ITG));
    original_mpcs.nodempc = allocate(product(3, (size_t)capacity), sizeof(ITG));
    original_mpcs.coef = allocate(capacity, sizeof(double));
    original_mpcs.labels = allocate(product(20, (size_t)nmpc), sizeof(char));
    if (nmpc > 0) {
        memcpy(original_mpcs.ipompc, ipompc, product((size_t)nmpc, sizeof(ITG)));
        memcpy(original_mpcs.labels, labels, product(20, (size_t)nmpc));
    }
    if (capacity > 0) {
        memcpy(original_mpcs.nodempc, nodempc, product(product(3, (size_t)capacity), sizeof(ITG)));
        memcpy(original_mpcs.coef, coef, product((size_t)capacity, sizeof(double)));
    }
}
static ITG read_identifier(FILE* input)
{
    char token[81], *end;
    long value;
    if (fscanf(input, "%80s", token) != 1) {
        fail("truncated integer field");
    }
    errno = 0;
    value = strtol(token, &end, 10);
    if (errno || *end || end == token || value < 1 || value > INT_MAX) {
        fail("invalid integer field");
    }
    return (ITG)value;
}
static void write_wrench(FILE* f, const char* kind, const char* name, const double* w)
{
    int j;
    for (j = 0; j < 6; j++) {
        if (!isfinite(w[j])) {
            fail("nonfinite native wrench");
        }
    }
    fprintf(f, "%s %s", kind, name);
    for (j = 0; j < 6; j++) {
        fprintf(f, " %.17g", w[j]);
    }
    fprintf(f, "\n");
}
static int face_compare(const void* aa, const void* bb)
{
    const Face *a = aa, *b = bb;
    int j;
    for (j = 0; j < 3; j++) {
        if (a->key[j] != b->key[j]) {
            return a->key[j] < b->key[j] ? -1 : 1;
        }
    }
    return 0;
}
static void sort3(ITG* a)
{
    ITG t;
    int i, j;
    for (i = 0; i < 3; i++) {
        for (j = i + 1; j < 3; j++) {
            if (a[i] > a[j]) {
                t = a[i];
                a[i] = a[j];
                a[j] = t;
            }
        }
    }
}
static ITG node_count(ITG element)
{
    char* label = &fa.lakon[8 * (size_t)element];
    if (strcmp1(label, "C3D4    ") == 0) {
        return 4;
    }
    if (strcmp1(label, "C3D10   ") == 0) {
        return 10;
    }
    return 0;
}
static void add_wrench(double* w, const double* position, const double* force)
{
    int j;
    for (j = 0; j < 3; j++) {
        w[j] += force[j];
    }
    w[3] += position[1] * force[2] - position[2] * force[1];
    w[4] += position[2] * force[0] - position[0] * force[2];
    w[5] += position[0] * force[1] - position[1] * force[0];
}
static ITG mpc_term(ITG identifier)
{
    if (identifier < 1 || identifier > fa.mpc_capacity) {
        fail("MPC term index is outside native storage");
    }
    return identifier - 1;
}
void fa_set_mpc_capacity(ITG capacity)
{
    if (!fa.active) {
        return;
    }
    /* Term links are 1-based; this bound also keeps every 3*index+2 access
     * representable in native ITG arithmetic after mpc_term validation.
     */
    if (capacity < 0 || capacity > INT_MAX / 3) {
        fail("invalid native MPC storage capacity");
    }
    fa.mpc_capacity = capacity;
}
void fa_check_contact_domain(ITG ntie, char* tieset, double* tietol, ITG mortar)
{
    ITG i;
    if (!fa.active) {
        return;
    }
    if (fa.version == 1 && ntie && mortar != 1) {
        fail("face-to-face penalty contact required");
    }
    for (i = 0; i < ntie; i++) {
        if (tieset[243 * (size_t)i + 80] == 'C' && mortar != 1) {
            fail("face-to-face penalty contact required");
        }
        if (fa.version >= 2 && tieset[243 * (size_t)i + 80] == 'T' &&
            tietol[4 * (size_t)i + 1] != -1.) {
            fail("original-coordinate MPC accounting requires ordinary Tie ADJUST=NO");
        }
    }
}
static ITG parent(const ITG* nodes, ITG count)
{
    Face key, *found;
    ITG index, start, end, i, j, nope;
    int matched;
    for (i = 0; i < 3; i++) {
        key.key[i] = nodes[i];
    }
    sort3(key.key);
    found = bsearch(&key, fa.faces, fa.nfaces, sizeof(Face), face_compare);
    if (!found) {
        fail("contact side has no structural face owner");
    }
    index = found - fa.faces;
    start = index;
    end = index + 1;
    while (start > 0 && !face_compare(&key, &fa.faces[start - 1])) {
        start--;
    }
    while (end < fa.nfaces && !face_compare(&key, &fa.faces[end])) {
        end++;
    }
    if (end - start != 1) {
        fail("contact side must have one exterior volume owner");
    }
    index = found->element;
    nope = node_count(index);
    for (i = 0; i < count; i++) {
        matched = 0;
        for (j = 0; j < nope; j++) {
            if (fa.kon[(size_t)fa.ipkon[index] + j] == nodes[i]) {
                matched = 1;
            }
        }
        if (!matched) {
            fail("contact face midside ownership mismatch");
        }
    }
    return index;
}
static int port_reference(ITG node)
{
    int i;
    for (i = 0; i < fa.np; i++) {
        if (fa.ports[i].ref == node) {
            return i;
        }
    }
    return -1;
}
static int port_rotation(ITG node)
{
    int i;
    for (i = 0; i < fa.np; i++) {
        if (fa.ports[i].rot == node) {
            return i;
        }
    }
    return -1;
}
static int angle_node(ITG node)
{
    int i;
    for (i = 0; i < fa.na; i++) {
        if (fa.angles[i].node == node) {
            return i;
        }
    }
    return -1;
}
static ITG original_term(ITG identifier)
{
    if (identifier < 1 || identifier > original_mpcs.capacity) {
        fail("original MPC term index is outside native storage");
    }
    return identifier - 1;
}
static void validate_angle(const Angle* angle)
{
    ITG row, first, index, visited, node, dir, matches = 0;
    double pivot, coefficients[3] = {0., 0., 0.};
    if (!original_mpcs.captured || original_mpcs.nk != fa.nk) {
        fail("original angular equation identity is unavailable");
    }
    for (row = 0; row < original_mpcs.nmpc; row++) {
        first = original_term(original_mpcs.ipompc[row]);
        index = first;
        visited = 0;
        for (;;) {
            if (++visited > original_mpcs.capacity) {
                fail("cyclic original angular equation term list");
            }
            if (original_mpcs.nodempc[3 * index] == angle->node &&
                original_mpcs.coef[index] != 0. &&
                (index != first || original_mpcs.nodempc[3 * index + 1] != 1)) {
                fail("angular auxiliary participates outside its defining dependent term");
            }
            if (!original_mpcs.nodempc[3 * index + 2]) {
                break;
            }
            index = original_term(original_mpcs.nodempc[3 * index + 2]);
        }
        if (original_mpcs.nodempc[3 * first] != angle->node ||
            original_mpcs.nodempc[3 * first + 1] != 1) {
            continue;
        }
        if (++matches != 1) {
            fail("angular auxiliary has repeated dependent equations");
        }
        pivot = original_mpcs.coef[first];
        if (!isfinite(pivot) || pivot == 0.) {
            fail("invalid angular auxiliary dependent coefficient");
        }
        index = first;
        visited = 0;
        while (original_mpcs.nodempc[3 * index + 2]) {
            if (++visited > original_mpcs.capacity) {
                fail("cyclic original angular equation term list");
            }
            index = original_term(original_mpcs.nodempc[3 * index + 2]);
            node = original_mpcs.nodempc[3 * index];
            dir = original_mpcs.nodempc[3 * index + 1];
            if (!isfinite(original_mpcs.coef[index])) {
                fail("nonfinite original angular equation coefficient");
            }
            if (original_mpcs.coef[index] == 0.) {
                continue;
            }
            if (node != angle->rot || dir < 1 || dir > 3) {
                fail("angular auxiliary equation is not bound only to its rotation port");
            }
            coefficients[dir - 1] += original_mpcs.coef[index] / pivot;
            if (!isfinite(coefficients[dir - 1])) {
                fail("nonfinite normalized angular equation");
            }
        }
    }
    if (matches != 1) {
        fail("angular auxiliary has no native defining equation");
    }
    for (dir = 0; dir < 3; dir++) {
        if (fabs(coefficients[dir] + angle->axis[dir]) > 1.e-12) {
            fail("angular auxiliary equation differs from its declared rotation axis");
        }
    }
}
static void validate_port(const Port* port)
{
    ITG row, first, index, visited, node, dir, translations = 0, rotations = 0;
    double pivot;
    int has_reference, has_rotation;
    if (!original_mpcs.captured || original_mpcs.nk != fa.nk) {
        fail("original native RBE identity is unavailable");
    }
    for (row = 0; row < original_mpcs.nmpc; row++) {
        if (strncmp(&original_mpcs.labels[20 * (size_t)row], "RIGID", 5)) {
            continue;
        }
        first = original_term(original_mpcs.ipompc[row]);
        node = original_mpcs.nodempc[3 * first] - 1;
        dir = original_mpcs.nodempc[3 * first + 1];
        pivot = original_mpcs.coef[first];
        if (node < 0 || node >= fa.nk || dir < 1 || dir > 3 ||
            !fa.structural_nodes[node] || !isfinite(pivot) || pivot == 0.) {
            continue;
        }
        index = first;
        visited = 0;
        has_reference = has_rotation = 0;
        for (;;) {
            if (++visited > original_mpcs.capacity) {
                fail("cyclic original RBE equation term list");
            }
            if (original_mpcs.nodempc[3 * index] == port->ref &&
                original_mpcs.nodempc[3 * index + 1] == dir &&
                isfinite(original_mpcs.coef[index]) &&
                fabs(original_mpcs.coef[index] / pivot + 1.) <= 1.e-12) {
                has_reference = 1;
            }
            if (original_mpcs.nodempc[3 * index] == port->rot &&
                original_mpcs.nodempc[3 * index + 1] >= 1 &&
                original_mpcs.nodempc[3 * index + 1] <= 3 &&
                isfinite(original_mpcs.coef[index]) && original_mpcs.coef[index] != 0.) {
                has_rotation |= 1 << (original_mpcs.nodempc[3 * index + 1] - 1);
            }
            if (!original_mpcs.nodempc[3 * index + 2]) {
                break;
            }
            index = original_term(original_mpcs.nodempc[3 * index + 2]);
        }
        if (has_reference && has_rotation) {
            translations |= 1 << (dir - 1);
            rotations |= has_rotation;
        }
    }
    if (translations != 7 || rotations != 7) {
        fail("declared port is not a finite native RBE receiving region");
    }
}
static void validate_composition(void)
{
    int i, j, p, left, right;
    double norm;
    for (i = 0; i < fa.np; i++) {
        Port* port = &fa.ports[i];
        if (port->ref > fa.nk || port->rot > fa.nk || port->ref == port->rot ||
            fa.structural_nodes[port->ref - 1] || fa.structural_nodes[port->rot - 1]) {
            fail("RBE port identities must be distinct detached native nodes");
        }
        for (j = 0; j < i; j++) {
            Port* other = &fa.ports[j];
            if (!strcmp(port->name, other->name) || port->ref == other->ref ||
                port->rot == other->rot || port->ref == other->rot || port->rot == other->ref) {
                fail("RBE port identities overlap");
            }
        }
        validate_port(port);
    }
    for (i = 0; i < fa.ns; i++) {
        p = port_reference(fa.supports[i].ref);
        if (p < 0 || fa.ports[p].rot != fa.supports[i].rot) {
            fail("V3 support must identify a declared native RBE port");
        }
        fa.ports[p].used = 1;
    }
    for (i = 0; i < fa.na; i++) {
        Angle* angle = &fa.angles[i];
        if (angle->node > fa.nk || fa.structural_nodes[angle->node - 1] ||
            port_reference(angle->node) >= 0 || port_rotation(angle->node) >= 0 ||
            port_rotation(angle->rot) < 0) {
            fail("angular auxiliary must be detached and identify one declared rotation port");
        }
        for (j = 0; j < i; j++) {
            if (fa.angles[j].node == angle->node) {
                fail("duplicate angular auxiliary identity");
            }
        }
        norm = 0.;
        for (j = 0; j < 3; j++) {
            if (!isfinite(angle->axis[j])) {
                fail("nonfinite angular auxiliary axis");
            }
            norm += angle->axis[j] * angle->axis[j];
        }
        if (!isfinite(norm) || fabs(norm - 1.) > 1.e-12) {
            fail("angular auxiliary axis must be a unit vector");
        }
        validate_angle(angle);
    }
    for (i = 0; i < fa.nsp; i++) {
        Spring* spring = &fa.springs[i];
        if (spring->element > fa.ne || fa.ipkon[spring->element - 1] < 0 ||
            strcmp1(&fa.lakon[8 * (size_t)(spring->element - 1)], "ESPRNG21") != 0) {
            fail("declared connector must be an active native SPRING2");
        }
        for (j = 0; j < i; j++) {
            if (fa.springs[j].element == spring->element) {
                fail("duplicate native connector identity");
            }
        }
        for (j = 0; j < 2; j++) {
            if (spring->nodes[j] > fa.nk || fa.structural_nodes[spring->nodes[j] - 1] ||
                fa.kon[(size_t)fa.ipkon[spring->element - 1] + j] != spring->nodes[j]) {
                fail("native connector endpoint identity or detached ownership differs");
            }
        }
        if (spring->nodes[0] == spring->nodes[1]) {
            fail("native connector endpoints must be distinct");
        }
        left = port_reference(spring->nodes[0]);
        right = port_reference(spring->nodes[1]);
        if (left >= 0 && right >= 0) {
            fa.ports[left].used = fa.ports[right].used = 1;
        }
        else {
            left = angle_node(spring->nodes[0]);
            right = angle_node(spring->nodes[1]);
            if (left < 0 || right < 0 || fa.angles[left].rot == fa.angles[right].rot) {
                fail("native connector must join two reference ports or two angular auxiliaries");
            }
            for (j = 0; j < 3; j++) {
                if (fabs(fa.angles[left].axis[j] - fa.angles[right].axis[j]) > 1.e-12) {
                    fail("native rotational connector axes differ");
                }
            }
            fa.angles[left].used = fa.angles[right].used = 1;
            fa.ports[port_rotation(fa.angles[left].rot)].used = 1;
            fa.ports[port_rotation(fa.angles[right].rot)].used = 1;
        }
    }
    for (i = 0; i < fa.np; i++) {
        if (!fa.ports[i].used) {
            fail("unused native RBE port declaration");
        }
    }
    for (i = 0; i < fa.na; i++) {
        if (!fa.angles[i].used) {
            fail("unused angular auxiliary declaration");
        }
    }
    for (i = 0; i < fa.nsp; i++) {
        if (!fa.springs[i].used) {
            fail("unused native connector declaration");
        }
    }
}
static void validate_spc_supports(
    ITG nboun, ITG* nodes, ITG* directions, double* values, ITG* amplitudes, char* types
)
{
    int i, j;
    ITG term, boundary, node, direction;
    unsigned char *selected, *states, *state, bit;
    enum { SPC_PRESENT = 1, SPC_REPEATED = 2, SPC_INVALID = 4 };
    if (!fa.nss) {
        return;
    }
    selected = allocate(fa.nk, sizeof(unsigned char));
    states = allocate(3 * (size_t)fa.nk, sizeof(unsigned char));
    for (boundary = 0; boundary < nboun; boundary++) {
        node = nodes[boundary];
        direction = directions[boundary];
        if (node < 1 || node > fa.nk || direction < 1 || direction > 3) {
            continue;
        }
        state = &states[3 * (size_t)(node - 1) + direction - 1];
        if (*state & SPC_PRESENT) {
            *state |= SPC_REPEATED;
        }
        *state |= SPC_PRESENT;
        if (!isfinite(values[boundary]) || values[boundary] != 0. ||
            (amplitudes && amplitudes[boundary]) || types[boundary] == 'R') {
            *state |= SPC_INVALID;
        }
    }
    for (i = 0; i < fa.nss; i++) {
        SPCSupport* support = &fa.spc_supports[i];
        for (j = 0; j < fa.ns; j++) {
            if (!strcmp(support->name, fa.supports[j].name)) {
                fail("SPC support identity duplicates an RBE support");
            }
        }
        for (j = 0; j < i; j++) {
            if (!strcmp(support->name, fa.spc_supports[j].name)) {
                fail("duplicate SPC support identity");
            }
        }
        for (term = 0; term < support->count; term++) {
            node = support->nodes[term];
            direction = support->directions[term];
            if (node > fa.nk || direction < 1 || direction > 3 ||
                !fa.structural_nodes[node - 1] || owner_any(fa.node_union, node - 1) ||
                port_reference(node) >= 0 || port_rotation(node) >= 0 || angle_node(node) >= 0) {
                fail("SPC support requires a structural translation outside every cut body and helper port");
            }
            bit = 1 << (direction - 1);
            if (selected[node - 1] & bit) {
                fail("SPC support degrees of freedom overlap");
            }
            selected[node - 1] |= bit;
            state = &states[3 * (size_t)(node - 1) + direction - 1];
            if (*state & SPC_INVALID) {
                fail("SPC support must be an original zero boundary without amplitude or RBE helper type");
            }
            if (!(*state & SPC_PRESENT) || (*state & SPC_REPEATED)) {
                fail("SPC support degree of freedom is missing or ambiguous in native boundaries");
            }
        }
    }
    free(selected);
    free(states);
}
void FORTRAN(
    fa_check_spring,
    (ITG * element, ITG* direction1, ITG* direction2, ITG* orientation, ITG* kind, ITG* tables,
     double* stiffness)
)
{
    int i;
    if (!fa.active || fa.version != 3) {
        return;
    }
    for (i = 0; i < fa.nsp; i++) {
        if (fa.springs[i].element == *element) {
            break;
        }
    }
    if (i == fa.nsp) {
        fail("native scalar spring force has no qualified connector declaration");
    }
    if (*kind != 2 || *tables != 1 || !isfinite(*stiffness) || *stiffness <= 0. ||
        *direction1 < 1 || *direction1 > 3 || *direction2 != *direction1) {
        fail("native connector requires one finite positive linear scalar spring law");
    }
    if (angle_node(fa.springs[i].nodes[0]) >= 0 &&
        (*direction1 != 1 || *direction2 != 1 || *orientation != 0)) {
        fail("native angular connector must act only on untransformed auxiliary angle DOF1");
    }
}
void fa_prepare(
    ITG nmethod,
    ITG* iperturb,
    ITG thermal,
    ITG ntrans,
    ITG mcs,
    ITG step,
    ITG nk,
    ITG ne,
    double* co,
    ITG* ipkon,
    ITG* kon,
    char* lakon,
    ITG nboun,
    ITG* nodeboun,
    ITG* ndirboun,
    double* xboun,
    ITG* iamboun,
    char* typeboun,
    ITG nmpc,
    ITG* ipompc,
    ITG* nodempc,
    ITG mpc_capacity
)
{
    const char* path = getenv("CCX_FORCE_ACCOUNTING_REQUEST");
    FILE* input;
    char token[81];
    ITG i, j, k, n, index, visited;
    size_t coordinate, word;
    unsigned char* cut;
    static const int face_nodes[4][3] = {{0, 1, 2}, {0, 3, 1}, {1, 3, 2}, {2, 3, 0}};
    if (!path) {
        return;
    }
    if (fa.active) {
        fail("only one step is supported");
    }
    if (nmethod != 1 || iperturb[1] != 0 || thermal > 1 || ntrans || mcs || step != 1) {
        fail("requires one small-displacement mechanical static step in global coordinates");
    }
    /* The largest mesh/result strides below are 3*nk and 12*ne. This also
     * bounds 4*ne faces, 8*element labels and 6*element load/contact offsets.
     * Connectivity offsets are promoted before adding local node indices.
     */
    if (nk < 1 || nk > INT_MAX / 3 || ne < 0 || ne > INT_MAX / 12) {
        fail("native mesh dimensions exceed the 32-bit accounting domain");
    }
    if (nmpc < 0 || nmpc > FA_MAX_MPC_ROWS || nmpc > mpc_capacity) {
        fail("native MPC row count exceeds supported native storage");
    }
    memset(&fa, 0, sizeof(fa));
    fa.active = 1;
    fa_set_mpc_capacity(mpc_capacity);
    fa.nk = nk;
    fa.ne = ne;
    fa.co = co;
    fa.ipkon = ipkon;
    fa.kon = kon;
    fa.lakon = lakon;
    fa.faces = allocate(4 * (size_t)ne, sizeof(Face));
    fa.loads = allocate(6 * (size_t)ne, sizeof(double));
    input = fopen(path, "r");
    if (!input) {
        fail("cannot read request");
    }
    if (fscanf(input, "%80s", token) != 1) {
        fail("unsupported request schema");
    }
    if (!strcmp(token, "CCX_FORCE_ACCOUNTING_V1")) {
        fa.version = 1;
    }
    else if (!strcmp(token, "CCX_FORCE_ACCOUNTING_V2")) {
        fa.version = 2;
    }
    else if (!strcmp(token, "CCX_FORCE_ACCOUNTING_V3")) {
        fa.version = 3;
        fa.budget = declaration_budget();
        fa.structural_nodes = allocate(nk, sizeof(unsigned char));
    }
    else {
        fail("unsupported request schema");
    }
    if (fa.version >= 2) {
        fa.original_co = allocate(3 * (size_t)nk, sizeof(double));
        for (coordinate = 0; coordinate < 3 * (size_t)nk; coordinate++) {
            if (!isfinite(co[coordinate])) {
                fail("nonfinite original reference coordinates");
            }
            fa.original_co[coordinate] = co[coordinate];
        }
        fa.co = fa.original_co;
    }
    for (;;) {
        if (fscanf(input, "%80s", token) != 1) {
            fail("truncated request");
        }
        if (!strcmp(token, "END")) {
            break;
        }
        if (!strcmp(token, "SUPPORT")) {
            Support* s;
            if (fa.version != 3 && fa.ns == FA_MAX) {
                fail("too many support requests");
            }
            admit_declaration("supports", (long long)fa.ns + fa.nss + 1);
            fa.supports = reserve_storage(fa.supports, &fa.supports_capacity, sizeof(Support), fa.ns);
            s = &fa.supports[fa.ns++];
            if (fscanf(input, "%80s", s->name) != 1) {
                fail("invalid support name");
            }
            s->ref = read_identifier(input);
            s->rot = read_identifier(input);
            if (s->ref < 1 || s->ref > nk || s->rot < 1 || s->rot > nk || s->ref == s->rot) {
                fail("invalid support ports");
            }
        }
        else if (fa.version == 3 && !strcmp(token, "SPC_SUPPORT")) {
            SPCSupport* support;
            admit_declaration("supports", (long long)fa.ns + fa.nss + 1);
            fa.spc_supports = reserve_storage(fa.spc_supports, &fa.spc_capacity, sizeof(SPCSupport), fa.nss);
            support = &fa.spc_supports[fa.nss++];
            if (fscanf(input, "%80s", support->name) != 1) {
                fail("invalid SPC support name");
            }
            support->count = read_identifier(input);
            if (support->count > nboun) {
                fail("SPC support term count exceeds native boundary count");
            }
            support->nodes = allocate(support->count, sizeof(ITG));
            support->directions = allocate(support->count, sizeof(ITG));
            for (j = 0; j < support->count; j++) {
                support->nodes[j] = read_identifier(input);
                support->directions[j] = read_identifier(input);
            }
        }
        else if (fa.version == 3 && !strcmp(token, "PORT")) {
            Port* port;
            admit_declaration("ports", (long long)fa.np + 1);
            fa.ports = reserve_storage(fa.ports, &fa.ports_capacity, sizeof(Port), fa.np);
            port = &fa.ports[fa.np++];
            if (fscanf(input, "%80s", port->name) != 1) {
                fail("invalid native RBE port name");
            }
            port->ref = read_identifier(input);
            port->rot = read_identifier(input);
        }
        else if (fa.version == 3 && !strcmp(token, "ANGLE")) {
            Angle* angle;
            admit_declaration("angles", (long long)fa.na + 1);
            fa.angles = reserve_storage(fa.angles, &fa.angles_capacity, sizeof(Angle), fa.na);
            angle = &fa.angles[fa.na++];
            angle->node = read_identifier(input);
            angle->rot = read_identifier(input);
            if (fscanf(input, "%lf %lf %lf", &angle->axis[0], &angle->axis[1], &angle->axis[2]) != 3) {
                fail("invalid angular auxiliary axis");
            }
        }
        else if (fa.version == 3 && !strcmp(token, "SPRING")) {
            Spring* spring;
            admit_declaration("springs", (long long)fa.nsp + 1);
            fa.springs = reserve_storage(fa.springs, &fa.springs_capacity, sizeof(Spring), fa.nsp);
            spring = &fa.springs[fa.nsp++];
            spring->element = read_identifier(input);
            spring->nodes[0] = read_identifier(input);
            spring->nodes[1] = read_identifier(input);
        }
        else if (!strcmp(token, "BODY")) {
            Body* b;
            if (fa.version != 3 && fa.nb == FA_MAX) {
                fail("too many body requests");
            }
            admit_declaration("bodies", (long long)fa.nb + 1);
            fa.bodies = reserve_storage(fa.bodies, &fa.bodies_capacity, sizeof(Body), fa.nb);
            b = &fa.bodies[fa.nb++];
            if (fscanf(input, "%80s", b->name) != 1) {
                fail("invalid body name");
            }
            b->ne = read_identifier(input);
            b->nn = read_identifier(input);
            if (b->ne > ne || b->nn < 3 || b->nn > nk) {
                fail("invalid body request");
            }
            b->elements = allocate(b->ne, sizeof(ITG));
            b->cut = allocate(b->nn, sizeof(ITG));
            for (j = 0; j < b->ne; j++) {
                n = read_identifier(input);
                if (n > ne || !node_count(n - 1) || ipkon[n - 1] < 0) {
                    fail("body must own active tetrahedra");
                }
                b->elements[j] = n;
            }
            for (j = 0; j < b->nn; j++) {
                n = read_identifier(input);
                if (n > nk) {
                    fail("invalid cut node");
                }
                b->cut[j] = n;
            }
        }
        else {
            fail("unknown request record");
        }
    }
    if (fscanf(input, "%80s", token) != EOF) {
        fail("trailing request data");
    }
    fclose(input);
    if (!fa.nb && !fa.ns && !fa.nss) {
        fail("empty request");
    }
    /* The final body count determines every ownership row's width. No matrix
     * is grown/repacked while callbacks or concurrent native force paths run.
     */
    fa.owner_words = fa.nb ? ((size_t)fa.nb + 63) / 64 : 1;
    fa.owners = allocate(product((size_t)ne, fa.owner_words), sizeof(uint64_t));
    fa.node_union = allocate(product((size_t)nk, fa.owner_words), sizeof(uint64_t));
    fa.node_intersection = allocate(product((size_t)nk, fa.owner_words), sizeof(uint64_t));
    fa.points = allocate(product(6, (size_t)fa.nb), sizeof(double));
    for (i = 0; i < nk; i++) {
        for (word = 0; word < fa.owner_words; word++) {
            owner_row(fa.node_intersection, i)[word] = UINT64_MAX;
        }
    }
    for (i = 0; i < fa.nb; i++) {
        Body* body = &fa.bodies[i];
        for (j = 0; j < body->ne; j++) {
            k = body->elements[j] - 1;
            if (owner_has(fa.owners, k, i)) {
                fail("duplicate body element");
            }
            owner_add(fa.owners, k, i);
        }
    }
    for (i = 0; i < fa.ns; i++) {
        for (j = 0; j < i; j++) {
            Support *a = &fa.supports[i], *b = &fa.supports[j];
            if (!strcmp(a->name, b->name) || a->ref == b->ref || a->rot == b->rot
                || a->ref == b->rot || a->rot == b->ref) {
                fail("support identities or ports overlap");
            }
        }
    }
    for (i = 0; i < fa.nb; i++) {
        for (j = 0; j < i; j++) {
            if (!strcmp(fa.bodies[i].name, fa.bodies[j].name)) {
                fail("duplicate body identity");
            }
        }
    }
    for (i = 0; i < ne; i++) {
        if (ipkon[i] < 0) {
            continue;
        }
        n = node_count(i);
        if (!n) {
            if (strcmp1(&lakon[8 * (size_t)i], "ESPRNGC") == 0) {
                continue;
            }
            if (fa.version == 3 && strcmp1(&lakon[8 * (size_t)i], "ESPRNG21") == 0) {
                for (j = 0; j < fa.nsp; j++) {
                    if (fa.springs[j].element == i + 1) {
                        fa.springs[j].used = 1;
                        break;
                    }
                }
                if (j == fa.nsp) {
                    fail("native SPRING2 has no qualified connector declaration");
                }
                continue;
            }
            fail("only C3D4/C3D10 volumes and face-to-face penalty contact are supported");
        }
        for (j = 0; j < n; j++) {
            k = kon[(size_t)ipkon[i] + j] - 1;
            if (fa.version == 3) {
                if (k < 0 || k >= nk) {
                    fail("native structural node identity is outside storage");
                }
                fa.structural_nodes[k] = 1;
            }
            for (word = 0; word < fa.owner_words; word++) {
                owner_row(fa.node_union, k)[word] |= owner_row(fa.owners, i)[word];
                owner_row(fa.node_intersection, k)[word] &= owner_row(fa.owners, i)[word];
            }
        }
        for (j = 0; j < 4; j++) {
            Face* f = &fa.faces[fa.nfaces++];
            f->element = i;
            for (k = 0; k < 3; k++) {
                f->key[k] = kon[(size_t)ipkon[i] + face_nodes[j][k]];
            }
            sort3(f->key);
        }
    }
    qsort(fa.faces, fa.nfaces, sizeof(Face), face_compare);
    if (fa.version == 3) {
        validate_composition();
        validate_spc_supports(nboun, nodeboun, ndirboun, xboun, iamboun, typeboun);
    }
    for (i = 0; i < fa.nb; i++) {
        Body* b = &fa.bodies[i];
        cut = allocate(nk, sizeof(unsigned char));
        for (j = 0; j < b->nn; j++) {
            k = b->cut[j] - 1;
            if (cut[k] || !owner_has(fa.node_union, k, i) || owner_has(fa.node_intersection, k, i)) {
                fail("cut nodes must uniquely identify the shared deformable interface");
            }
            cut[k] = 1;
        }
        for (j = 0; j < nk; j++) {
            if (owner_has(fa.node_union, j, i) && !owner_has(fa.node_intersection, j, i) && !cut[j]) {
                fail("body has an undeclared shared-node interface");
            }
        }
        for (j = 0; j < nboun; j++) {
            if (owner_has(fa.node_union, nodeboun[j] - 1, i)) {
                fail("cut body contains a prescribed degree of freedom");
            }
        }
        for (j = 0; j < nmpc; j++) {
            index = mpc_term(ipompc[j]);
            visited = 0;
            for (;;) {
                if (++visited > fa.mpc_capacity) {
                    fail("cyclic native MPC term list");
                }
                k = nodempc[3 * index] - 1;
                if (k < 0 || k >= nk) {
                    fail("MPC node identity is outside native storage");
                }
                if (owner_has(fa.node_union, k, i)) {
                    if (fa.version == 1) {
                        fail("cut body intersects an MPC");
                    }
                    if (!owner_has(fa.node_intersection, k, i)) {
                        fail("MPC intersects an ambiguously owned shared cut node");
                    }
                }
                if (!nodempc[3 * index + 2]) {
                    break;
                }
                index = mpc_term(nodempc[3 * index + 2]);
            }
        }
        free(cut);
    }
    if (fa.version == 3) {
        printf("CCX_FORCE_ACCOUNTING_CAPACITY_APPLIED_V1 {\"budget\":%d,"
               "\"counts\":{\"supports\":%d,\"bodies\":%d,\"ports\":%d,\"angles\":%d,\"springs\":%d},"
               "\"total\":%d}\n", fa.budget, fa.ns + fa.nss, fa.nb, fa.np, fa.na, fa.nsp, fa.declarations);
        fflush(stdout);
    }
}
int fa_active(void)
{
    return fa.active;
}
void fa_reset_loads(void)
{
    if (fa.active) {
        memset(fa.loads, 0, 6 * (size_t)fa.ne * sizeof(double));
        memset(fa.points, 0, product(product(6, (size_t)fa.nb), sizeof(double)));
    }
}
void FORTRAN(fa_elementload, (ITG * element, ITG* count, ITG* nodes, double* ff))
{
    ITG j, e = *element - 1;
    if (!fa.active) {
        return;
    }
    if (e < 0 || e >= fa.ne || !node_count(e)) {
        return;
    }
    for (j = 0; j < *count; j++) {
        add_wrench(&fa.loads[6 * e], &fa.co[3 * (nodes[j] - 1)], &ff[3 * j]);
    }
}
void fa_pointloads(ITG count, ITG* nodes, ITG* directions, double* values)
{
    ITG i, j, node;
    double f[3];
    if (!fa.active) {
        return;
    }
    for (i = 0; i < count; i++) {
        node = nodes[2 * (size_t)i] - 1;
        if (node < 0 || node >= fa.nk) {
            fail("concentrated load node is outside native storage");
        }
        for (j = 0; j < fa.nb; j++) {
            if (!owner_has(fa.node_union, node, j) || values[i] == 0.) {
                continue;
            }
            if (!owner_has(fa.node_intersection, node, j)) {
                fail("point load on cut has ambiguous body ownership");
            }
            if (directions[i] < 1 || directions[i] > 3) {
                fail("unsupported concentrated moment");
            }
            memset(f, 0, sizeof(f));
            f[directions[i] - 1] = values[i];
            add_wrench(&fa.points[6 * (size_t)j], &fa.co[3 * node], f);
        }
    }
}
static ITG contact_capacity;
void fa_begin_results(ITG ne, ITG* ipkon, ITG* kon, char* lakon, double* co)
{
    size_t coordinate;
    if (!fa.active) {
        return;
    }
    if (ne < 0 || ne > INT_MAX / 12) {
        fail("native result dimensions exceed the 32-bit accounting domain");
    }
    if (fa.version >= 2) {
        for (coordinate = 0; coordinate < 3 * (size_t)fa.nk; coordinate++) {
            if (co[coordinate] != fa.original_co[coordinate]) {
                fail("native reference coordinates changed after accounting preparation");
            }
        }
    }
    fa.ipkon = ipkon;
    fa.kon = kon;
    fa.lakon = lakon;
    fa.co = fa.version >= 2 ? fa.original_co : co;
    free(fa.contacts);
    free(fa.contact_owners);
    contact_capacity = ne;
    fa.contacts = allocate(12 * (size_t)ne, sizeof(double));
    fa.contact_owners = allocate(product(2 * (size_t)ne, fa.owner_words), sizeof(uint64_t));
}
void FORTRAN(fa_contact, (ITG * element, ITG* count, ITG* nodes, double* fnl, char* label))
{
    ITG master, j, e = *element - 1, side, owner;
    double force[3];
    if (!fa.active) {
        return;
    }
    if (e < 0 || e >= contact_capacity) {
        fail("contact indexing changed during force calculation");
    }
    master = label[7] - '0';
    if ((master != 3 && master != 6) || (*count - master != 3 && *count - master != 6)) {
        fail("only triangular tetrahedron face contact is supported");
    }
    for (side = 0; side < 2; side++) {
        owner = parent(&nodes[side ? master : 0], side ? *count - master : master);
        memcpy(owner_row(fa.contact_owners, 2 * (size_t)e + side), owner_row(fa.owners, owner),
               fa.owner_words * sizeof(uint64_t));
        for (j = side ? master : 0; j < (side ? *count : master); j++) {
            force[0] = -fnl[3 * j];
            force[1] = -fnl[3 * j + 1];
            force[2] = -fnl[3 * j + 2];
            add_wrench(&fa.contacts[12 * e + 6 * side], &fa.co[3 * (nodes[j] - 1)], force);
        }
    }
}
static ITG* validate_mpcs(
    ITG nk,
    ITG mt,
    ITG* nactdof,
    ITG nmpc,
    ITG* ipompc,
    ITG* nodempc,
    double* coef
)
{
    unsigned char* terms;
    ITG *dependent, *incoming, *order;
    ITG i, j, index, node, dir, first, row, head = 0, tail = 0;
    size_t dof;
    if (nmpc < 0 || nmpc > FA_MAX_MPC_ROWS || nmpc > fa.mpc_capacity || mt < 4) {
        fail("unsupported native MPC or degree-of-freedom dimensions");
    }
    for (node = 0; node < nk; node++) {
        if (!owner_any(fa.node_union, node)) {
            continue;
        }
        for (dir = 1; dir <= 3; dir++) {
            index = nactdof[mt * (size_t)node + dir];
            if (index < 0 && !(index % 2)) {
                fail("cut body contains a prescribed degree of freedom at the output state");
            }
        }
    }
    dependent = allocate(3 * (size_t)nk, sizeof(ITG));
    incoming = allocate(nmpc, sizeof(ITG));
    order = allocate(nmpc, sizeof(ITG));
    terms = allocate(fa.mpc_capacity, sizeof(unsigned char));
    for (i = 0; i < nmpc; i++) {
        index = mpc_term(ipompc[i]);
        node = nodempc[3 * index] - 1;
        dir = nodempc[3 * index + 1];
        if (node < 0 || node >= nk || dir < 1 || dir > 3) {
            fail("invalid native MPC dependent degree of freedom");
        }
        dof = 3 * (size_t)node + dir - 1;
        if (dependent[dof] || nactdof[mt * (size_t)node + dir] != -2 * i - 1) {
            fail("MPC dependent degrees of freedom are not uniquely active");
        }
        if (!isfinite(coef[index]) || coef[index] == 0.) {
            fail("unsupported MPC dependent coefficient");
        }
        dependent[dof] = i + 1;
    }
    for (i = 0; i < nmpc; i++) {
        index = mpc_term(ipompc[i]);
        first = 1;
        for (;;) {
            if (terms[index]) {
                fail("native MPC term lists overlap or contain a cycle");
            }
            terms[index] = 1;
            node = nodempc[3 * index] - 1;
            dir = nodempc[3 * index + 1];
            if (node < 0 || node >= nk || dir < 1 || dir > 3 || !isfinite(coef[index])) {
                fail("invalid native MPC term or coefficient");
            }
            dof = 3 * (size_t)node + dir - 1;
            if (!first && nactdof[mt * (size_t)node + dir] < 0 &&
                nactdof[mt * (size_t)node + dir] % 2 && !dependent[dof]) {
                fail("native MPC dependent degree-of-freedom mapping is inconsistent");
            }
            if (!first && coef[index] != 0. && dependent[dof]) {
                row = dependent[dof] - 1;
                if (row == i) {
                    fail("native MPC dependency graph contains a self-reference");
                }
                incoming[row]++;
            }
            for (j = 0; j < fa.nb; j++) {
                if (!owner_has(fa.node_union, node, j)) {
                    continue;
                }
                if (!owner_has(fa.node_intersection, node, j)) {
                    fail("MPC intersects an ambiguously owned shared cut node");
                }
                if (nactdof[mt * (size_t)node + dir] < 0 &&
                    !(nactdof[mt * (size_t)node + dir] % 2)) {
                    fail("cut body contains an MPC-coupled prescribed degree of freedom");
                }
            }
            first = 0;
            if (!nodempc[3 * index + 2]) {
                break;
            }
            index = mpc_term(nodempc[3 * index + 2]);
        }
    }
    /* A row whose dependent DOF occurs in no other unresolved row can be
     * eliminated first. This solves C_D^T lambda = r_D, including native
     * Tie-to-RBE chains left undecascaded by the nonlinear contact path.
     * Exact zero coefficients do not create graph edges or transfers.
     */
    for (i = 0; i < nmpc; i++) {
        if (!incoming[i]) {
            order[tail++] = i;
        }
    }
    while (head < tail) {
        i = order[head++];
        index = mpc_term(ipompc[i]);
        while (nodempc[3 * index + 2]) {
            index = mpc_term(nodempc[3 * index + 2]);
            node = nodempc[3 * index] - 1;
            dir = nodempc[3 * index + 1];
            dof = 3 * (size_t)node + dir - 1;
            if (coef[index] != 0. && dependent[dof]) {
                row = dependent[dof] - 1;
                if (--incoming[row] == 0) {
                    order[tail++] = row;
                }
            }
        }
    }
    if (head != nmpc) {
        fail("native MPC dependency graph contains a nonzero cycle");
    }
    free(terms);
    free(dependent);
    free(incoming);
    return order;
}
static void add_mpc_force(double* vector, size_t index, double force)
{
    if (!isfinite(force) || !isfinite(vector[index] + force)) {
        fail("nonfinite native MPC nodal contribution");
    }
    vector[index] += force;
}
void fa_emit(
    double* fn,
    double* external,
    ITG nk,
    ITG mt,
    ITG* nactdof,
    ITG nmpc,
    ITG* ipompc,
    ITG* nodempc,
    double* coef,
    double* v,
    ITG step,
    ITG inc,
    double time
)
{
    const char* path = getenv("CCX_FORCE_ACCOUNTING_REQUEST");
    char* output;
    FILE* f;
    double *residual, *mpc = NULL, force, couple[3], w[6], load[6], contact[6], transfer[6], nodal[3];
    ITG *order = NULL, i, j, k, index, start, node, dir, row;
    if (!fa.active) {
        return;
    }
    if (!external || nk != fa.nk) {
        fail("native load vector or node identity unavailable");
    }
    if (nk < 1 || mt < 4 || nk > INT_MAX / mt) {
        fail("native nodal dimensions exceed the 32-bit accounting domain");
    }
    if (nmpc < 0 || nmpc > FA_MAX_MPC_ROWS || nmpc > fa.mpc_capacity) {
        fail("native MPC row count exceeds supported output-state storage");
    }
    if (fa.version >= 2) {
        order = validate_mpcs(nk, mt, nactdof, nmpc, ipompc, nodempc, coef);
        mpc = allocate((size_t)mt * nk, sizeof(double));
    }
    if (fa.version == 3) {
        for (i = 0; i < fa.na; i++) {
            node = fa.angles[i].node - 1;
            index = mt * node + 1;
            if (nactdof[index] >= 0 || !(nactdof[index] % 2) || !isfinite(v[index])) {
                fail("angular auxiliary must retain its native dependent angle degree of freedom");
            }
            for (dir = 2; dir <= 3; dir++) {
                index = mt * node + dir;
                if (nactdof[index] >= 0 || nactdof[index] % 2 || v[index] != 0.) {
                    fail("angular auxiliary unused degrees of freedom must be prescribed at zero");
                }
            }
        }
    }
    residual = allocate((size_t)mt * nk, sizeof(double));
    for (i = 0; i < mt * nk; i++) {
        residual[i] = fn[i] - external[i];
        if (fa.version >= 2 && !isfinite(residual[i])) {
            fail("nonfinite native physical nodal residual");
        }
    }
    /* V2 eliminates an acyclic native MPC graph in validated topological
     * order; V1 retains the original support-projection order. Accumulate
     * C^T lambda at its actual nodal locations, separately from the projected
     * residual used for support reactions. This is the total nodal MPC
     * contribution, not a per-Tie row force.
     */
    for (i = 0; i < nmpc; i++) {
        row = order ? order[i] : i;
        start = mpc_term(ipompc[row]);
        node = nodempc[3 * start] - 1;
        dir = nodempc[3 * start + 1];
        if (dir < 1 || dir > 3 || coef[start] == 0.) {
            fail("unsupported MPC degree of freedom or coefficient");
        }
        force = residual[mt * node + dir] / coef[start];
        if (mpc) {
            if (!isfinite(force)) {
                fail("nonfinite native MPC multiplier");
            }
            add_mpc_force(mpc, mt * (size_t)node + dir, coef[start] * force);
        }
        residual[mt * node + dir] = 0.;
        index = nodempc[3 * start + 2];
        while (index) {
            index = mpc_term(index);
            node = nodempc[3 * index] - 1;
            dir = nodempc[3 * index + 1];
            if (dir < 1 || dir > 3) {
                fail("unsupported MPC independent degree of freedom");
            }
            residual[mt * node + dir] -= coef[index] * force;
            if (mpc) {
                if (!isfinite(residual[mt * node + dir])) {
                    fail("nonfinite projected native nodal residual");
                }
                add_mpc_force(mpc, mt * (size_t)node + dir, coef[index] * force);
            }
            index = nodempc[3 * index + 2];
        }
    }
    output = allocate(strlen(path) + 5, 1);
    sprintf(output, "%s.out", path);
    f = fopen(output, "w");
    if (!f) {
        fail("cannot create output");
    }
    fprintf(f, "CCX_FORCE_ACCOUNTING_V%d\nSTATE %d %d %.17g\n", fa.version, (int)step, (int)inc, time);
    for (i = 0; i < fa.ns; i++) {
        Support* s = &fa.supports[i];
        memset(w, 0, sizeof(w));
        for (j = 1; j <= 3; j++) {
            node = s->ref - 1;
            index = mt * node + j;
            if (nactdof[index] >= 0 || nactdof[index] % 2 || v[index] != 0.) {
                fail("support reference must be fully prescribed at zero");
            }
            w[j - 1] = residual[index];
            node = s->rot - 1;
            index = mt * node + j;
            if (nactdof[index] >= 0 || nactdof[index] % 2 || v[index] != 0.) {
                fail("support rotation must be fully prescribed at zero");
            }
            couple[j - 1] = residual[index];
        }
        w[3] = couple[0] + fa.co[3 * (s->ref - 1) + 1] * w[2] - fa.co[3 * (s->ref - 1) + 2] * w[1];
        w[4] = couple[1] + fa.co[3 * (s->ref - 1) + 2] * w[0] - fa.co[3 * (s->ref - 1)] * w[2];
        w[5] = couple[2] + fa.co[3 * (s->ref - 1)] * w[1] - fa.co[3 * (s->ref - 1) + 1] * w[0];
        write_wrench(f, "SUPPORT", s->name, w);
    }
    if (fa.version == 3) {
        for (i = 0; i < fa.nss; i++) {
            SPCSupport* support = &fa.spc_supports[i];
            memset(w, 0, sizeof(w));
            for (j = 0; j < support->count; j++) {
                node = support->nodes[j] - 1;
                dir = support->directions[j];
                index = mt * node + dir;
                if (nactdof[index] >= 0 || nactdof[index] % 2 || v[index] != 0.) {
                    fail("SPC support degree of freedom must remain prescribed at zero");
                }
                memset(nodal, 0, sizeof(nodal));
                nodal[dir - 1] = residual[index];
                add_wrench(w, &fa.co[3 * (size_t)node], nodal);
            }
            write_wrench(f, "SUPPORT", support->name, w);
        }
    }
    for (i = 0; i < fa.nb; i++) {
        Body* b = &fa.bodies[i];
        memcpy(load, &fa.points[6 * (size_t)i], sizeof(load));
        memset(contact, 0, sizeof(contact));
        memset(transfer, 0, sizeof(transfer));
        for (j = 0; j < b->ne; j++) {
            for (k = 0; k < 6; k++) {
                load[k] += fa.loads[6 * (b->elements[j] - 1) + k];
            }
        }
        for (j = 0; j < 2 * contact_capacity; j++) {
            if (owner_has(fa.contact_owners, j, i)) {
                for (k = 0; k < 6; k++) {
                    contact[k] += fa.contacts[6 * j + k];
                }
            }
        }
        if (mpc) {
            for (j = 0; j < nk; j++) {
                if (owner_has(fa.node_intersection, j, i) && owner_has(fa.node_union, j, i)) {
                    add_wrench(transfer, &fa.co[3 * (size_t)j], &mpc[mt * (size_t)j + 1]);
                }
            }
        }
        for (j = 0; j < 6; j++) {
            w[j] = -load[j] - contact[j] - transfer[j];
        }
        write_wrench(f, "CUT", b->name, w);
        write_wrench(f, "LOAD", b->name, load);
        write_wrench(f, "CONTACT", b->name, contact);
        if (fa.version >= 2) {
            write_wrench(f, "MPC", b->name, transfer);
        }
    }
    fprintf(f, "END\n");
    if (fclose(f)) {
        fail("output write failed");
    }
    free(output);
    free(residual);
    free(mpc);
    free(order);
}
