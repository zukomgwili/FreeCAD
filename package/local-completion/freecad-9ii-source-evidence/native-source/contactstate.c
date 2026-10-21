/* SPDX-License-Identifier: GPL-2.0-only
 * Included by forceaccounting.c. Read-only native penalty-contact diagnostics.
 * No constitutive value, constraint, contact pairing or convergence control is
 * assigned by this module. Its activation and wire are independent of V3.
 */
#include <ctype.h>

typedef struct
{
    char name[81], slave[81], master[81];
    ITG tie;
} CSPair;

typedef struct
{
    ITG pair, point, local, slave_element, slave_face, master_element, master_face;
    int generated, evaluated, tangential, branch, elastic_override, paired;
    double slave[3], master[3], normal[3], tangent1[3], tangent2[3];
    double slave_parameters[2], master_parameters[2];
    double clearance, pressure, displacement[2], shear[2];
    double plastic_increment, plastic_vector[3], weight, area;
} CSSample;

typedef struct
{
    ITG step, increment;
    double time;
    size_t count;
    CSSample* samples;
} CSFrame;

typedef struct
{
    ITG pair, element, face, points;
} CSFace;

static struct
{
    int active, capturing;
    char* path;
    char request[33];
    ITG nk, ne, ntie;
    size_t pair_count, point_count, frame_count, inventory_count, face_count;
    double end_time;
    double* original_co;
    CSPair* pairs;
    CSSample* points;
    CSSample* inventory;
    CSFace* faces;
    CSFrame* frames;
} cs;

static void cs_fail(const char* message)
{
    fprintf(stderr, "*ERROR CCX contact state V1: %s\n", message);
    exit(201);
}

static void* cs_allocate(size_t count, size_t size)
{
    void* value;
    if (size && count > SIZE_MAX / size) {
        cs_fail("allocation dimension overflow");
    }
    value = calloc(count ? count : 1, size);
    if (!value) {
        cs_fail("allocation failed");
    }
    return value;
}

static int cs_identifier(const char* name)
{
    const unsigned char* p = (const unsigned char*)name;
    if (!*p) {
        return 0;
    }
    for (; *p; p++) {
        if (!((*p >= 'A' && *p <= 'Z') || (*p >= 'a' && *p <= 'z') ||
              (*p >= '0' && *p <= '9') || *p == '_' || *p == '-' || *p == '.')) {
            return 0;
        }
    }
    return 1;
}

static void cs_surface(char result[81], const char* native)
{
    size_t i = 0;
    while (i < 81 && native[i] != ' ') {
        i++;
    }
    if (i < 2 || native[i - 1] != 'T') {
        cs_fail("selected pair is not an element-face penalty pair");
    }
    memcpy(result, native, i - 1);
    result[i - 1] = '\0';
}

static int cs_same_name(const char* left, const char* right)
{
    while (*left && *right) {
        if (toupper((unsigned char)*left++) != toupper((unsigned char)*right++)) {
            return 0;
        }
    }
    return *left == *right;
}

static void cs_token(FILE* f, char result[81])
{
    if (fscanf(f, "%80s", result) != 1) {
        cs_fail("truncated request");
    }
}

void cs_prepare(ITG method, ITG* perturb, ITG thermal, ITG transforms, ITG cyclic,
                ITG step, ITG nk, ITG ne, double* co, ITG* ipkon, char* lakon,
                ITG ntie, char* tieset, double* tietol, ITG mortar,
                ITG ncmat, ITG ntmat, double* elcon)
{
    const char* path = getenv("CCX_CONTACT_STATE_REQUEST");
    FILE* f;
    char token[81], slave[81], master[81];
    size_t i, j;
    ITG tie, found, material;
    if (!path) {
        return;
    }
    if (!*path || cs.active) {
        cs_fail("requires a nonempty request path and one standalone step");
    }
    if (method != 1 || perturb[1] || thermal > 1 || transforms || cyclic || step != 1 ||
        mortar != 1) {
        cs_fail("requires one small-displacement global mechanical static face-to-face penalty step");
    }
    if (nk < 1 || nk > INT_MAX / 3 || ne < 1 || ne > INT_MAX / 12 || ntie < 1 ||
        ntie > INT_MAX / 243 || ncmat < 3 || ntmat < 1) {
        cs_fail("unsupported native dimensions");
    }
    for (tie = 0; tie < ne; tie++) {
        if (ipkon[tie] < 0) {
            continue;
        }
        if (strncmp(&lakon[8 * (size_t)tie], "C3D4", 4) &&
            strncmp(&lakon[8 * (size_t)tie], "C3D10", 5)) {
            cs_fail("only tetrahedral structural elements are supported");
        }
    }
    f = fopen(path, "r");
    if (!f) {
        cs_fail("cannot read request");
    }
    cs_token(f, token);
    if (strcmp(token, "CCX_CONTACT_STATE_V1")) {
        cs_fail("unsupported request schema");
    }
    cs_token(f, token);
    if (strcmp(token, "REQUEST")) {
        cs_fail("missing request identity");
    }
    cs_token(f, token);
    if (strlen(token) != 32) {
        cs_fail("request identity must be 32 lowercase hexadecimal characters");
    }
    for (i = 0; i < 32; i++) {
        if (!(token[i] >= '0' && token[i] <= '9') && !(token[i] >= 'a' && token[i] <= 'f')) {
            cs_fail("request identity must be 32 lowercase hexadecimal characters");
        }
    }
    memcpy(cs.request, token, 33);
    cs_token(f, token);
    if (strcmp(token, "END_TIME") || fscanf(f, "%lf", &cs.end_time) != 1 ||
        !isfinite(cs.end_time) || cs.end_time <= 0.) {
        cs_fail("requires a finite positive requested end time");
    }
    cs_token(f, token);
    if (strcmp(token, "UNITS")) {
        cs_fail("missing declared writer units");
    }
    cs_token(f, token);
    if (strcmp(token, "MM")) {
        cs_fail("requires declared MM N MPA writer units");
    }
    cs_token(f, token);
    if (strcmp(token, "N")) {
        cs_fail("requires declared MM N MPA writer units");
    }
    cs_token(f, token);
    if (strcmp(token, "MPA")) {
        cs_fail("requires declared MM N MPA writer units");
    }
    cs.pairs = cs_allocate(ntie, sizeof(CSPair));
    for (;;) {
        CSPair* pair;
        cs_token(f, token);
        if (!strcmp(token, "END")) {
            break;
        }
        if (strcmp(token, "PAIR") || cs.pair_count >= (size_t)ntie) {
            cs_fail("invalid or excessive pair request");
        }
        pair = &cs.pairs[cs.pair_count];
        cs_token(f, pair->name);
        cs_token(f, pair->slave);
        cs_token(f, pair->master);
        if (!cs_identifier(pair->name) || !cs_identifier(pair->slave) ||
            !cs_identifier(pair->master)) {
            cs_fail("pair identifiers must be ASCII letters, digits, underscore, hyphen or dot");
        }
        found = 0;
        for (tie = 0; tie < ntie; tie++) {
            if (tieset[243 * (size_t)tie + 80] != 'C') {
                continue;
            }
            cs_surface(slave, &tieset[243 * (size_t)tie + 81]);
            cs_surface(master, &tieset[243 * (size_t)tie + 162]);
            if (cs_same_name(slave, pair->slave) && cs_same_name(master, pair->master)) {
                pair->tie = tie;
                found++;
            }
        }
        if (found != 1) {
            cs_fail("requested pair must identify exactly one native slave/master declaration");
        }
        for (i = 0; i < cs.pair_count; i++) {
            if (!strcmp(cs.pairs[i].name, pair->name) || cs.pairs[i].tie == pair->tie) {
                cs_fail("duplicate contact name or native pair request");
            }
        }
        material = (ITG)tietol[4 * (size_t)pair->tie + 1];
        if (material < 1) {
            cs_fail("selected native contact material is unavailable");
        }
        i = (size_t)(ncmat + 1) * ntmat * (material - 1);
        if (!isfinite(elcon[i + 3]) || elcon[i + 3] < 1. || elcon[i + 3] >= 4.) {
            cs_fail("only ordinary penalty contact laws are supported; tied contact is not admitted");
        }
        if (ncmat >= 7 && (!isfinite(elcon[i + 6]) || elcon[i + 6] < 0. ||
            (elcon[i + 6] > 0. && (!isfinite(elcon[i + 7]) || elcon[i + 7] <= 0.)))) {
            cs_fail("unsupported native friction definition");
        }
        cs.pair_count++;
    }
    if (!cs.pair_count || fscanf(f, "%80s", token) != EOF || ferror(f) || fclose(f)) {
        cs_fail("empty request, trailing data or request read failure");
    }
    cs.nk = nk;
    cs.ne = ne;
    cs.ntie = ntie;
    cs.original_co = cs_allocate(3 * (size_t)nk, sizeof(double));
    for (j = 0; j < 3 * (size_t)nk; j++) {
        if (!isfinite(co[j])) {
            cs_fail("nonfinite native reference coordinates");
        }
        cs.original_co[j] = co[j];
    }
    cs.path = cs_allocate(strlen(path) + 1, 1);
    strcpy(cs.path, path);
    cs.active = 1;
}

static ITG cs_face(ITG element, ITG face, ITG* ipkon, ITG* kon, char* lakon, ITG nodes[6])
{
    static const int local[4][6] = {
        {1, 3, 2, 7, 6, 5}, {1, 2, 4, 5, 9, 8},
        {2, 3, 4, 6, 10, 9}, {1, 4, 3, 8, 10, 7}
    };
    ITG count, i, node;
    if (element < 1 || element > cs.ne || face < 1 || face > 4 || ipkon[element - 1] < 0) {
        cs_fail("selected contact face is outside the original tetrahedral mesh");
    }
    if (!strncmp(&lakon[8 * (size_t)(element - 1)], "C3D10", 5)) {
        count = 6;
    }
    else if (!strncmp(&lakon[8 * (size_t)(element - 1)], "C3D4", 4)) {
        count = 3;
    }
    else {
        cs_fail("selected contact face is not tetrahedral");
        return 0;
    }
    for (i = 0; i < count; i++) {
        node = kon[(size_t)ipkon[element - 1] + local[face - 1][i] - 1];
        if (node < 1 || node > cs.nk) {
            cs_fail("selected native face has an invalid node");
        }
        nodes[i] = node;
    }
    return count;
}

static void cs_point(ITG count, ITG nodes[6], double xi, double eta, double* co,
                     double* v, ITG mt, double* adjustment, double reltime, double point[3])
{
    double xl[18], shape[42], jacobian[3], derivatives[21];
    ITG i, j, flag = 1;
    if (!isfinite(xi) || !isfinite(eta)) {
        cs_fail("nonfinite native contact parametric coordinates");
    }
    for (i = 0; i < count; i++) {
        for (j = 0; j < 3; j++) {
            xl[3 * i + j] = co[3 * (size_t)(nodes[i] - 1) + j] +
                v[mt * (size_t)(nodes[i] - 1) + j + 1] +
                (adjustment ? adjustment[3 * i + j] * reltime : 0.);
        }
    }
    if (count == 6) {
        FORTRAN(shape6tri, (&xi, &eta, xl, jacobian, derivatives, shape, &flag));
    }
    else {
        FORTRAN(shape3tri, (&xi, &eta, xl, jacobian, derivatives, shape, &flag));
    }
    for (j = 0; j < 3; j++) {
        point[j] = 0.;
        for (i = 0; i < count; i++) {
            point[j] += shape[7 * i + 3] * xl[3 * i + j];
        }
        if (!isfinite(point[j])) {
            cs_fail("nonfinite native contact point");
        }
    }
}

static void cs_basis(CSSample* sample)
{
    double length = 0.;
    ITG j;
    if (1. - fabs(sample->normal[0]) < 1.5231e-6) {
        sample->tangent1[0] = -sample->normal[2] * sample->normal[0];
        sample->tangent1[1] = -sample->normal[2] * sample->normal[1];
        sample->tangent1[2] = 1. - sample->normal[2] * sample->normal[2];
    }
    else {
        sample->tangent1[0] = 1. - sample->normal[0] * sample->normal[0];
        sample->tangent1[1] = -sample->normal[0] * sample->normal[1];
        sample->tangent1[2] = -sample->normal[0] * sample->normal[2];
    }
    for (j = 0; j < 3; j++) {
        length += sample->tangent1[j] * sample->tangent1[j];
    }
    length = sqrt(length);
    if (!isfinite(length) || length <= 0.) {
        cs_fail("invalid native contact normal");
    }
    for (j = 0; j < 3; j++) {
        sample->tangent1[j] /= length;
    }
    sample->tangent2[0] = sample->normal[1] * sample->tangent1[2] -
        sample->normal[2] * sample->tangent1[1];
    sample->tangent2[1] = sample->normal[2] * sample->tangent1[0] -
        sample->normal[0] * sample->tangent1[2];
    sample->tangent2[2] = sample->normal[0] * sample->tangent1[1] -
        sample->normal[1] * sample->tangent1[0];
}

void cs_begin_results(ITG iout, ITG nk, ITG ne, ITG mt, double* co, double* v,
                      ITG* ipkon, ITG* kon, char* lakon, ITG* itiefac,
                      ITG* islavsurf, double* pslavsurf, double* pmastsurf,
                      double* clearini, double* springarea, double reltime)
{
    size_t p, coordinate, maximum = 0, face_count = 0, face_index = 0;
    ITG face, start, end, point, encoded, nodes[6], count, i, e, index, total;
    CSSample* sample;
    cs.capturing = 0;
    if (!cs.active || iout != 2) {
        return;
    }
    if (nk != cs.nk || ne < cs.ne || mt < 4 || mt > INT_MAX / nk || !isfinite(reltime)) {
        cs_fail("native result dimensions changed");
    }
    for (coordinate = 0; coordinate < 3 * (size_t)nk; coordinate++) {
        if (co[coordinate] != cs.original_co[coordinate]) {
            cs_fail("native reference coordinates changed after preparation");
        }
    }
    for (p = 0; p < cs.pair_count; p++) {
        start = itiefac[2 * (size_t)cs.pairs[p].tie];
        end = itiefac[2 * (size_t)cs.pairs[p].tie + 1];
        if (start < 1 || end < start || end > INT_MAX / 27) {
            cs_fail("selected native slave surface is empty or invalid");
        }
        if ((size_t)(end - start + 1) > SIZE_MAX - face_count) {
            cs_fail("native face inventory dimension overflow");
        }
        face_count += end - start + 1;
        for (face = start; face <= end; face++) {
            point = islavsurf[2 * (size_t)face + 1];
            if (point < 0 || point > INT_MAX / 6) {
                cs_fail("native contact point dimension overflow");
            }
            if ((size_t)point > maximum) {
                maximum = point;
            }
        }
    }
    if (!cs.frame_count) {
        free(cs.faces);
        cs.faces = cs_allocate(face_count, sizeof(CSFace));
        cs.face_count = face_count;
    }
    else if (face_count != cs.face_count) {
        cs_fail("selected native contact face inventory changed between retained frames");
    }
    free(cs.points);
    cs.points = cs_allocate(maximum, sizeof(CSSample));
    cs.point_count = maximum;
    for (p = 0; p < cs.pair_count; p++) {
        start = itiefac[2 * (size_t)cs.pairs[p].tie];
        end = itiefac[2 * (size_t)cs.pairs[p].tie + 1];
        for (face = start; face <= end; face++) {
            ITG first = islavsurf[2 * (size_t)(face - 1) + 1];
            ITG last = islavsurf[2 * (size_t)face + 1];
            if (first < 0 || last < first || (size_t)last > maximum) {
                cs_fail("invalid native slave integration-point range");
            }
            encoded = islavsurf[2 * (size_t)(face - 1)];
            if (!cs.frame_count) {
                cs.faces[face_index].pair = p + 1;
                cs.faces[face_index].element = encoded / 10;
                cs.faces[face_index].face = encoded % 10;
                cs.faces[face_index].points = last - first;
            }
            else if (cs.faces[face_index].pair != (ITG)p + 1 ||
                     cs.faces[face_index].element != encoded / 10 ||
                     cs.faces[face_index].face != encoded % 10 ||
                     cs.faces[face_index].points != last - first) {
                cs_fail("selected native sample label/count inventory changed between retained frames");
            }
            face_index++;
            for (point = first; point < last; point++) {
                sample = &cs.points[point];
                if (sample->pair) {
                    cs_fail("native contact sample belongs to more than one selected pair");
                }
                sample->pair = p + 1;
                sample->point = point + 1;
                sample->local = point - first + 1;
                sample->slave_element = encoded / 10;
                sample->slave_face = encoded % 10;
                sample->slave_parameters[0] = pslavsurf[3 * (size_t)point];
                sample->slave_parameters[1] = pslavsurf[3 * (size_t)point + 1];
                sample->weight = pslavsurf[3 * (size_t)point + 2];
                if (!isfinite(sample->weight) || sample->weight <= 0.) {
                    cs_fail("invalid native contact integration weight");
                }
                count = cs_face(sample->slave_element, sample->slave_face, ipkon, kon, lakon, nodes);
                cs_point(count, nodes, pslavsurf[3 * (size_t)point],
                         pslavsurf[3 * (size_t)point + 1], co, v, mt,
                         &clearini[27 * (size_t)(face - 1)], reltime, sample->slave);
                if (!isfinite(pmastsurf[6 * (size_t)point + 2]) ||
                    pmastsurf[6 * (size_t)point + 2] < 0. ||
                    pmastsurf[6 * (size_t)point + 2] > INT_MAX) {
                    cs_fail("invalid native master face identity");
                }
                encoded = (ITG)pmastsurf[6 * (size_t)point + 2];
                if (encoded) {
                    sample->paired = 1;
                    sample->master_element = encoded / 10;
                    sample->master_face = encoded % 10;
                    sample->master_parameters[0] = pmastsurf[6 * (size_t)point];
                    sample->master_parameters[1] = pmastsurf[6 * (size_t)point + 1];
                    count = cs_face(sample->master_element, sample->master_face, ipkon, kon, lakon, nodes);
                    cs_point(count, nodes, pmastsurf[6 * (size_t)point],
                             pmastsurf[6 * (size_t)point + 1], co, v, mt,
                             NULL, reltime, sample->master);
                    sample->clearance = 0.;
                    for (i = 0; i < 3; i++) {
                        sample->normal[i] = pmastsurf[6 * (size_t)point + 3 + i];
                        if (!isfinite(sample->normal[i])) {
                            cs_fail("nonfinite native master normal");
                        }
                        sample->clearance += (sample->slave[i] - sample->master[i]) * sample->normal[i];
                    }
                    sample->clearance -= springarea[2 * (size_t)point + 1] * (1. - reltime);
                    sample->area = springarea[2 * (size_t)point];
                    if (!isfinite(sample->clearance) || !isfinite(sample->area) || sample->area <= 0.) {
                        cs_fail("nonfinite clearance or invalid native representative area");
                    }
                    cs_basis(sample);
                }
                encoded = islavsurf[2 * (size_t)(face - 1)];
            }
        }
    }
    for (e = cs.ne; e < ne; e++) {
        if (ipkon[e] < 1 || strncmp(&lakon[8 * (size_t)e], "ESPRNGC", 7)) {
            cs_fail("unexpected generated native element");
        }
        index = ipkon[e];
        total = kon[index - 1];
        if (total < 6 || total > 12 || index > INT_MAX - total - 3) {
            cs_fail("invalid generated contact connectivity");
        }
        point = kon[(size_t)index + total];
        if (point < 1) {
            cs_fail("invalid generated native contact point");
        }
        if ((size_t)point <= maximum && cs.points[point - 1].pair) {
            sample = &cs.points[point - 1];
            if (!sample->paired || sample->generated) {
                cs_fail("generated native contact sample has missing or duplicate identity");
            }
            sample->generated = 1;
        }
    }
    cs.capturing = 1;
}

static CSSample* cs_sample(ITG point)
{
    if (!cs.capturing || point < 1 || (size_t)point > cs.point_count || !cs.points[point - 1].pair) {
        return NULL;
    }
    if (!cs.points[point - 1].generated) {
        cs_fail("contact-law callback has no generated native sample");
    }
    return &cs.points[point - 1];
}

void FORTRAN(cs_normal, (ITG* point, double* slave, double* master, double* normal,
                         double* clearance, double* pressure, double* area))
{
    CSSample* sample = cs_sample(*point);
    ITG j;
    if (!sample) {
        return;
    }
    if (sample->evaluated || !isfinite(*clearance) || !isfinite(*pressure) ||
        !isfinite(*area) || *area <= 0.) {
        cs_fail("duplicate or nonfinite native normal contact evaluation");
    }
    for (j = 0; j < 3; j++) {
        if (!isfinite(slave[j]) || !isfinite(master[j]) || !isfinite(normal[j])) {
            cs_fail("nonfinite native contact geometry");
        }
        sample->slave[j] = slave[j];
        sample->master[j] = master[j];
        sample->normal[j] = normal[j];
    }
    sample->clearance = *clearance;
    sample->pressure = *pressure;
    sample->area = *area;
    sample->evaluated = 1;
    cs_basis(sample);
}

void FORTRAN(cs_stick, (ITG* point, ITG* elastic))
{
    CSSample* sample = cs_sample(*point);
    if (sample) {
        sample->branch = 1;
        sample->elastic_override = *elastic == 1;
        sample->plastic_increment = 0.;
    }
}

void FORTRAN(cs_slip, (ITG* point, double* increment, double* direction))
{
    CSSample* sample = cs_sample(*point);
    ITG j;
    if (!sample) {
        return;
    }
    if (!isfinite(*increment) || *increment < 0.) {
        cs_fail("invalid native plastic slip increment");
    }
    sample->branch = 2;
    sample->plastic_increment = *increment;
    for (j = 0; j < 3; j++) {
        sample->plastic_vector[j] = *increment * direction[j];
        if (!isfinite(sample->plastic_vector[j])) {
            cs_fail("nonfinite native plastic slip vector");
        }
    }
}

void FORTRAN(cs_tangent, (ITG* point, double* coefficient, double* first, double* second,
                          double* displacement, double* shear))
{
    CSSample* sample = cs_sample(*point);
    ITG j;
    if (!sample || *coefficient <= 0.) {
        return;
    }
    if (!sample->branch) {
        cs_fail("native tangential evaluation has no constitutive branch");
    }
    for (j = 0; j < 3; j++) {
        if (!isfinite(first[j]) || !isfinite(second[j])) {
            cs_fail("nonfinite native contact tangent");
        }
        sample->tangent1[j] = first[j];
        sample->tangent2[j] = second[j];
    }
    for (j = 0; j < 2; j++) {
        if (!isfinite(displacement[j]) || !isfinite(shear[j])) {
            cs_fail("nonfinite native tangential contact output");
        }
        sample->displacement[j] = displacement[j];
        sample->shear[j] = shear[j];
    }
    sample->tangential = 1;
}

static void cs_vector(FILE* f, const double* vector, int available, ITG count)
{
    ITG j;
    if (!available) {
        fputs("null", f);
        return;
    }
    fputc('[', f);
    for (j = 0; j < count; j++) {
        if (!isfinite(vector[j])) {
            cs_fail("nonfinite value cannot be serialized");
        }
        fprintf(f, "%s%.17g", j ? "," : "", vector[j]);
    }
    fputc(']', f);
}

void cs_emit(ITG step, ITG increment, double time)
{
    FILE* f;
    char *output, *temporary;
    size_t p, n, i, j;
    CSFrame* frame;
    CSSample* sample;
    if (!cs.capturing) {
        return;
    }
    cs.capturing = 0;
    if (step != 1 || increment < 1 || !isfinite(time) || time <= 0. || time > cs.end_time) {
        cs_fail("retained output has invalid step, increment or time");
    }
    n = 0;
    for (p = 0; p < cs.point_count; p++) {
        sample = &cs.points[p];
        if (sample->pair) {
            if (sample->generated && !sample->evaluated) {
                cs_fail("generated native sample was not evaluated at retained output");
            }
            n++;
        }
    }
    if (!cs.frame_count) {
        cs.inventory = cs_allocate(n, sizeof(CSSample));
        cs.inventory_count = n;
    }
    else if (n != cs.inventory_count) {
        cs_fail("native sample inventory changed between retained frames");
    }
    n = 0;
    for (p = 0; p < cs.point_count; p++) {
        CSSample* original;
        sample = &cs.points[p];
        if (!sample->pair) {
            continue;
        }
        original = &cs.inventory[n++];
        if (!cs.frame_count) {
            *original = *sample;
        }
        else if (original->pair != sample->pair || original->point != sample->point ||
                 original->local != sample->local || original->slave_element != sample->slave_element ||
                 original->slave_face != sample->slave_face) {
            cs_fail("native sample identity changed between retained frames");
        }
    }
    if (cs.frame_count && cs.frames[cs.frame_count - 1].increment == increment &&
        cs.frames[cs.frame_count - 1].time == time) {
        frame = &cs.frames[cs.frame_count - 1];
        free(frame->samples);
    }
    else {
        CSFrame* replacement;
        if (cs.frame_count && (cs.frames[cs.frame_count - 1].increment >= increment ||
            cs.frames[cs.frame_count - 1].time > time)) {
            cs_fail("retained native increments must increase and cumulative time must not decrease");
        }
        replacement = cs_allocate(cs.frame_count + 1, sizeof(CSFrame));
        if (cs.frame_count) {
            memcpy(replacement, cs.frames, cs.frame_count * sizeof(CSFrame));
        }
        free(cs.frames);
        cs.frames = replacement;
        frame = &cs.frames[cs.frame_count++];
    }
    frame->step = step;
    frame->increment = increment;
    frame->time = time;
    frame->count = n;
    frame->samples = cs_allocate(n, sizeof(CSSample));
    n = 0;
    for (p = 0; p < cs.point_count; p++) {
        if (cs.points[p].pair) {
            frame->samples[n++] = cs.points[p];
        }
    }
    output = cs_allocate(strlen(cs.path) + 5, 1);
    temporary = cs_allocate(strlen(cs.path) + 9, 1);
    sprintf(output, "%s.out", cs.path);
    sprintf(temporary, "%s.out.tmp", cs.path);
    f = fopen(temporary, "w");
    if (!f) {
        cs_fail("cannot create diagnostic output");
    }
    fprintf(f, "{\"schema\":\"CCX_CONTACT_STATE_V1\",\"request\":\"%s\","
            "\"complete\":%s,\"units\":{\"length\":\"mm\",\"force\":\"N\",\"stress\":\"MPa\"},"
            "\"position_frame\":\"CURRENT_WITH_NATIVE_CLEARANCE_ADJUSTMENT\","
            "\"basis_frame\":\"NATIVE_MASTER_NORMAL\","
            "\"sample_identity_scope\":\"FRAME_LOCAL_NATIVE_CATALOGUE\",\"face_inventory\":[",
            cs.request, time == cs.end_time ? "true" : "false");
    for (i = 0; i < cs.face_count; i++) {
        CSFace* face = &cs.faces[i];
        fprintf(f, "%s{\"contact\":\"%s\",\"native_pair\":%d,\"slave_element\":%d,"
                "\"slave_face\":%d,\"expected_points\":%d}", i ? "," : "",
                cs.pairs[face->pair - 1].name, (int)cs.pairs[face->pair - 1].tie + 1,
                (int)face->element, (int)face->face, (int)face->points);
    }
    fputs("],\"sample_inventory\":[", f);
    for (i = 0; i < cs.inventory_count; i++) {
        sample = &cs.inventory[i];
        fprintf(f, "%s{\"contact\":\"%s\",\"native_pair\":%d,\"slave_element\":%d,"
                "\"slave_face\":%d,\"native_point\":%d,\"local_point\":%d}", i ? "," : "",
                cs.pairs[sample->pair - 1].name, (int)cs.pairs[sample->pair - 1].tie + 1,
                (int)sample->slave_element, (int)sample->slave_face,
                (int)sample->point, (int)sample->local);
    }
    fputs("],\"frames\":[", f);
    for (i = 0; i < cs.frame_count; i++) {
        frame = &cs.frames[i];
        fprintf(f, "%s{\"step\":%d,\"increment\":%d,\"time\":%.17g,"
                "\"success\":true,\"complete\":%s,\"samples\":[",
                i ? "," : "", (int)frame->step, (int)frame->increment, frame->time,
                frame->time == cs.end_time ? "true" : "false");
        for (j = 0; j < frame->count; j++) {
            const char *availability, *state, *evaluation, *engagement;
            sample = &frame->samples[j];
            availability = sample->generated ? "ACTIVE" : (sample->paired ? "INACTIVE" : "UNPAIRED");
            state = !sample->generated ? "UNAVAILABLE" : (!sample->tangential ? "FRICTIONLESS" :
                (sample->elastic_override ? "ELASTIC_OVERRIDE" : (sample->branch == 1 ? "STICK" : "SLIP")));
            evaluation = sample->generated ? "NATIVE_CONTACT_LAW" :
                (sample->paired ? "NATIVE_PRESERVED_PROJECTION" : "UNAVAILABLE");
            engagement = sample->generated ? "ACTIVE" : (!sample->paired ? "UNAVAILABLE" :
                (sample->clearance > 0. ? "OPEN_AT_PRESERVED_PROJECTION" : "INACTIVE"));
            fprintf(f, "%s{\"contact\":\"%s\",\"native_pair\":%d,\"slave_element\":%d,"
                    "\"slave_face\":%d,\"native_point\":%d,\"local_point\":%d,"
                    "\"availability\":\"%s\",\"state\":\"%s\",\"evaluation\":\"%s\","
                    "\"engagement\":\"%s\",\"master_element\":",
                    j ? "," : "", cs.pairs[sample->pair - 1].name,
                    (int)cs.pairs[sample->pair - 1].tie + 1, (int)sample->slave_element,
                    (int)sample->slave_face, (int)sample->point, (int)sample->local,
                    availability, state, evaluation, engagement);
            if (sample->paired) {
                fprintf(f, "%d,\"master_face\":%d,\"clearance\":%.17g,\"area\":%.17g",
                        (int)sample->master_element, (int)sample->master_face,
                        sample->clearance, sample->area);
            }
            else {
                fputs("null,\"master_face\":null,\"clearance\":null,\"area\":null", f);
            }
            fprintf(f, ",\"weight\":%.17g,\"pressure\":", sample->weight);
            if (sample->generated) {
                fprintf(f, "%.17g", sample->pressure);
            }
            else {
                fputs("null", f);
            }
            fputs(",\"slave_position\":", f);
            cs_vector(f, sample->slave, 1, 3);
            fputs(",\"slave_parameters\":", f);
            cs_vector(f, sample->slave_parameters, 1, 2);
            fputs(",\"master_position\":", f);
            cs_vector(f, sample->master, sample->paired, 3);
            fputs(",\"master_parameters\":", f);
            cs_vector(f, sample->master_parameters, sample->paired, 2);
            fputs(",\"normal\":", f);
            cs_vector(f, sample->normal, sample->paired, 3);
            fputs(",\"tangent1\":", f);
            cs_vector(f, sample->tangent1, sample->paired, 3);
            fputs(",\"tangent2\":", f);
            cs_vector(f, sample->tangent2, sample->paired, 3);
            fputs(",\"tangential_displacement\":", f);
            cs_vector(f, sample->displacement, sample->tangential, 2);
            fputs(",\"shear\":", f);
            cs_vector(f, sample->shear, sample->tangential, 2);
            fputs(",\"plastic_slip_increment\":", f);
            if (sample->tangential) {
                fprintf(f, "%.17g", sample->plastic_increment);
            }
            else {
                fputs("null", f);
            }
            fputs(",\"plastic_slip_vector\":", f);
            cs_vector(f, sample->plastic_vector, sample->tangential, 3);
            fputc('}', f);
        }
        fputs("]}", f);
    }
    fputs("]}\n", f);
    if (ferror(f) || fclose(f) || rename(temporary, output)) {
        cs_fail("diagnostic output write or atomic publication failed");
    }
    free(output);
    free(temporary);
}
