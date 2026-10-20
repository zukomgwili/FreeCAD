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
    ITG *elements, *cut, ne, nn;
} Body;
static struct
{
    int active, version, ns, nb;
    ITG nk, ne, nfaces, mpc_capacity;
    double *co, *loads, *contacts;
    ITG *ipkon, *kon;
    char* lakon;
    uint64_t *owners, *node_union, *node_intersection, *contact_owners;
    Face* faces;
    Support supports[FA_MAX];
    Body bodies[FA_MAX];
    double points[FA_MAX][6];
} fa;

static void fail(const char* message)
{
    fprintf(stderr, "*ERROR CCX force accounting V%d: %s\n", fa.version ? fa.version : 1, message);
    exit(201);
}
static void* allocate(size_t count, size_t size)
{
    void* p = calloc(count ? count : 1, size);
    if (!p) {
        fail("allocation failed");
    }
    return p;
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
    char* label = &fa.lakon[8 * element];
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
    if (capacity < 0) {
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
        if (fa.version == 2 && tieset[243 * (size_t)i + 80] == 'T' &&
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
            if (fa.kon[fa.ipkon[index] + j] == nodes[i]) {
                matched = 1;
            }
        }
        if (!matched) {
            fail("contact face midside ownership mismatch");
        }
    }
    return index;
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
    uint64_t bit;
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
    memset(&fa, 0, sizeof(fa));
    fa.active = 1;
    fa_set_mpc_capacity(mpc_capacity);
    fa.nk = nk;
    fa.ne = ne;
    fa.co = co;
    fa.ipkon = ipkon;
    fa.kon = kon;
    fa.lakon = lakon;
    fa.owners = allocate(ne, sizeof(uint64_t));
    fa.node_union = allocate(nk, sizeof(uint64_t));
    fa.node_intersection = allocate(nk, sizeof(uint64_t));
    for (i = 0; i < nk; i++) {
        fa.node_intersection[i] = UINT64_MAX;
    }
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
    else {
        fail("unsupported request schema");
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
            if (fa.ns == FA_MAX) {
                fail("too many support requests");
            }
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
        else if (!strcmp(token, "BODY")) {
            Body* b;
            if (fa.nb == FA_MAX) {
                fail("too many body requests");
            }
            b = &fa.bodies[fa.nb];
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
            bit = UINT64_C(1) << fa.nb++;
            for (j = 0; j < b->ne; j++) {
                n = read_identifier(input);
                if (n > ne || !node_count(n - 1) || ipkon[n - 1] < 0) {
                    fail("body must own active tetrahedra");
                }
                if (fa.owners[n - 1] & bit) {
                    fail("duplicate body element");
                }
                b->elements[j] = n;
                fa.owners[n - 1] |= bit;
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
    if (!fa.nb && !fa.ns) {
        fail("empty request");
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
            if (strcmp1(&lakon[8 * i], "ESPRNGC") == 0) {
                continue;
            }
            fail("only C3D4/C3D10 volumes and face-to-face penalty contact are supported");
        }
        for (j = 0; j < n; j++) {
            k = kon[ipkon[i] + j] - 1;
            fa.node_union[k] |= fa.owners[i];
            fa.node_intersection[k] &= fa.owners[i];
        }
        for (j = 0; j < 4; j++) {
            Face* f = &fa.faces[fa.nfaces++];
            f->element = i;
            for (k = 0; k < 3; k++) {
                f->key[k] = kon[ipkon[i] + face_nodes[j][k]];
            }
            sort3(f->key);
        }
    }
    qsort(fa.faces, fa.nfaces, sizeof(Face), face_compare);
    for (i = 0; i < fa.nb; i++) {
        Body* b = &fa.bodies[i];
        bit = UINT64_C(1) << i;
        cut = allocate(nk, sizeof(unsigned char));
        for (j = 0; j < b->nn; j++) {
            k = b->cut[j] - 1;
            if (cut[k] || !(fa.node_union[k] & bit) || (fa.node_intersection[k] & bit)) {
                fail("cut nodes must uniquely identify the shared deformable interface");
            }
            cut[k] = 1;
        }
        for (j = 0; j < nk; j++) {
            if ((fa.node_union[j] & bit) && !(fa.node_intersection[j] & bit) && !cut[j]) {
                fail("body has an undeclared shared-node interface");
            }
        }
        for (j = 0; j < nboun; j++) {
            if (fa.node_union[nodeboun[j] - 1] & bit) {
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
                if (fa.node_union[k] & bit) {
                    if (fa.version == 1) {
                        fail("cut body intersects an MPC");
                    }
                    if (!(fa.node_intersection[k] & bit)) {
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
}
int fa_active(void)
{
    return fa.active;
}
void fa_reset_loads(void)
{
    if (fa.active) {
        memset(fa.loads, 0, 6 * (size_t)fa.ne * sizeof(double));
        memset(fa.points, 0, sizeof(fa.points));
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
    uint64_t bit;
    if (!fa.active) {
        return;
    }
    for (i = 0; i < count; i++) {
        node = nodes[2 * i] - 1;
        for (j = 0; j < fa.nb; j++) {
            bit = UINT64_C(1) << j;
            if (!(fa.node_union[node] & bit) || values[i] == 0.) {
                continue;
            }
            if (!(fa.node_intersection[node] & bit)) {
                fail("point load on cut has ambiguous body ownership");
            }
            if (directions[i] < 1 || directions[i] > 3) {
                fail("unsupported concentrated moment");
            }
            memset(f, 0, sizeof(f));
            f[directions[i] - 1] = values[i];
            add_wrench(fa.points[j], &fa.co[3 * node], f);
        }
    }
}
static ITG contact_capacity;
void fa_begin_results(ITG ne, ITG* ipkon, ITG* kon, char* lakon, double* co)
{
    if (!fa.active) {
        return;
    }
    fa.ipkon = ipkon;
    fa.kon = kon;
    fa.lakon = lakon;
    fa.co = co;
    free(fa.contacts);
    free(fa.contact_owners);
    contact_capacity = ne;
    fa.contacts = allocate(12 * (size_t)ne, sizeof(double));
    fa.contact_owners = allocate(2 * (size_t)ne, sizeof(uint64_t));
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
        fa.contact_owners[2 * e + side] = fa.owners[owner];
        for (j = side ? master : 0; j < (side ? *count : master); j++) {
            force[0] = -fnl[3 * j];
            force[1] = -fnl[3 * j + 1];
            force[2] = -fnl[3 * j + 2];
            add_wrench(&fa.contacts[12 * e + 6 * side], &fa.co[3 * (nodes[j] - 1)], force);
        }
    }
}
static void validate_mpcs(
    ITG nk,
    ITG mt,
    ITG* nactdof,
    ITG nmpc,
    ITG* ipompc,
    ITG* nodempc,
    double* coef
)
{
    unsigned char *dependent, *terms;
    ITG i, j, index, node, dir, first;
    uint64_t bit;
    size_t dof;
    if (nmpc < 0 || nmpc > (INT_MAX - 1) / 2 || mt < 4) {
        fail("unsupported native MPC or degree-of-freedom dimensions");
    }
    for (node = 0; node < nk; node++) {
        if (!fa.node_union[node]) {
            continue;
        }
        for (dir = 1; dir <= 3; dir++) {
            index = nactdof[mt * (size_t)node + dir];
            if (index < 0 && !(index % 2)) {
                fail("cut body contains a prescribed degree of freedom at the output state");
            }
        }
    }
    dependent = allocate(3 * (size_t)nk, sizeof(unsigned char));
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
        dependent[dof] = 1;
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
            if (!first && (dependent[dof] ||
                (nactdof[mt * (size_t)node + dir] < 0 &&
                 nactdof[mt * (size_t)node + dir] % 2))) {
                fail("MPC terms are not fully decascaded at the output state");
            }
            for (j = 0; j < fa.nb; j++) {
                bit = UINT64_C(1) << j;
                if (!(fa.node_union[node] & bit)) {
                    continue;
                }
                if (!(fa.node_intersection[node] & bit)) {
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
    free(terms);
    free(dependent);
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
    double *residual, *mpc = NULL, force, couple[3], w[6], load[6], contact[6], transfer[6];
    ITG i, j, k, index, start, node, dir;
    uint64_t bit;
    if (!fa.active) {
        return;
    }
    if (!external || nk != fa.nk) {
        fail("native load vector or node identity unavailable");
    }
    if (nk < 1 || mt < 4 || nk > INT_MAX / mt) {
        fail("native nodal dimensions exceed the 32-bit accounting domain");
    }
    if (fa.version == 2) {
        validate_mpcs(nk, mt, nactdof, nmpc, ipompc, nodempc, coef);
        mpc = allocate((size_t)mt * nk, sizeof(double));
    }
    residual = allocate((size_t)mt * nk, sizeof(double));
    for (i = 0; i < mt * nk; i++) {
        residual[i] = fn[i] - external[i];
        if (fa.version == 2 && !isfinite(residual[i])) {
            fail("nonfinite native physical nodal residual");
        }
    }
    /* For fully decascaded constraints, each dependent residual determines
     * one multiplier. Accumulate C^T lambda at its actual nodal locations,
     * separately from the projected residual used for support reactions.
     * This is the total nodal MPC contribution, not a per-Tie row force.
     */
    for (i = 0; i < nmpc; i++) {
        start = ipompc[i] - 1;
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
        index = nodempc[3 * start + 2] - 1;
        while (index >= 0) {
            node = nodempc[3 * index] - 1;
            dir = nodempc[3 * index + 1];
            if (dir < 1 || dir > 3) {
                fail("unsupported MPC independent degree of freedom");
            }
            residual[mt * node + dir] -= coef[index] * force;
            if (mpc) {
                add_mpc_force(mpc, mt * (size_t)node + dir, coef[index] * force);
            }
            index = nodempc[3 * index + 2] - 1;
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
    for (i = 0; i < fa.nb; i++) {
        Body* b = &fa.bodies[i];
        bit = UINT64_C(1) << i;
        memcpy(load, fa.points[i], sizeof(load));
        memset(contact, 0, sizeof(contact));
        memset(transfer, 0, sizeof(transfer));
        for (j = 0; j < b->ne; j++) {
            for (k = 0; k < 6; k++) {
                load[k] += fa.loads[6 * (b->elements[j] - 1) + k];
            }
        }
        for (j = 0; j < 2 * contact_capacity; j++) {
            if (fa.contact_owners[j] & bit) {
                for (k = 0; k < 6; k++) {
                    contact[k] += fa.contacts[6 * j + k];
                }
            }
        }
        if (mpc) {
            for (j = 0; j < nk; j++) {
                if (fa.node_intersection[j] & fa.node_union[j] & bit) {
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
        if (fa.version == 2) {
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
}
