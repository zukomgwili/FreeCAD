/* SPDX-License-Identifier: GPL-2.0-only
 * ARTIFICIAL NATIVE CAPACITY/MASK UNIT, NOT PHYSICAL QUALIFICATION.
 *
 * This translation unit includes the ACTUAL production implementation and must
 * link the real CalculiX strcmp1.o, with that source tree's CalculiX.h available.
 * No solver, spring/contact constitutive law, real displacement solution or
 * engineering equilibrium is qualified by manufactured callback forces.
 *
 * The private-static access is deliberate and limited to a component arithmetic
 * unit. Real native-CAD/solver fixtures remain the public-interface acceptance
 * gate. Every nonzero expected wrench below is a fixed small-integer literal.
 */
#define _POSIX_C_SOURCE 200809L
#ifndef FREECAD_FORCE_ACCOUNTING_SOURCE
#error "Define FREECAD_FORCE_ACCOUNTING_SOURCE as the actual production C path"
#endif
#include FREECAD_FORCE_ACCOUNTING_SOURCE
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#define UNIT_BODIES 264
#define UNIT_MT 4
#define UNIT_WORDS 5

enum { UNIT_CUT, UNIT_LOAD, UNIT_CONTACT, UNIT_MPC, UNIT_KINDS };

typedef struct {
    ITG regions, nk, ne;
    ITG *ipkon, *kon, *active;
    char* lakon;
    double *coordinates, *internal, *external, *displacement;
} UnitMesh;

static double expected[UNIT_BODIES][UNIT_KINDS][6];

static void unit_fail(const char* reason)
{
    fprintf(stderr, "ARTIFICIAL_NATIVE_CAPACITY_MASK_UNIT_FAILURE: %s\n", reason);
    exit(2);
}

static void check(int condition, const char* reason)
{
    if (!condition) {
        unit_fail(reason);
    }
}

static FILE* create_new_request(const char* path)
{
    int descriptor;
    FILE* stream;
    struct stat state;
    char* output = allocate(strlen(path) + 5, 1);
    sprintf(output, "%s.out", path);
    errno = 0;
    check(lstat(output, &state) == -1 && errno == ENOENT,
          "unit output path already exists or cannot be checked");
    free(output);
    descriptor = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
    check(descriptor >= 0, "unit request must be a new private file");
    stream = fdopen(descriptor, "w");
    check(stream != NULL, "cannot open new unit request stream");
    return stream;
}

static void make_mesh(UnitMesh* mesh, ITG regions)
{
    ITG region, node, dir, active = 1;
    static const double positions[5][3] = {
        {1, 3, 5}, {1, 4, 5}, {1, 3, 6}, {2, 3, 5}, {0, 3, 5}
    };
    memset(mesh, 0, sizeof(*mesh));
    mesh->regions = regions;
    mesh->nk = 5 * regions;
    mesh->ne = 2 * regions;
    mesh->ipkon = allocate(mesh->ne, sizeof(ITG));
    mesh->kon = allocate(4 * (size_t)mesh->ne, sizeof(ITG));
    mesh->lakon = allocate(8 * (size_t)mesh->ne, sizeof(char));
    mesh->coordinates = allocate(3 * (size_t)mesh->nk, sizeof(double));
    mesh->active = allocate(UNIT_MT * (size_t)mesh->nk, sizeof(ITG));
    mesh->internal = allocate(UNIT_MT * (size_t)mesh->nk, sizeof(double));
    mesh->external = allocate(UNIT_MT * (size_t)mesh->nk, sizeof(double));
    mesh->displacement = allocate(UNIT_MT * (size_t)mesh->nk, sizeof(double));
    for (region = 0; region < regions; region++) {
        ITG base = 5 * region;
        ITG element = 2 * region;
        /* Two tetrahedra share nodes 1/2/3; only the first is BODY-owned.
         * IDs, not coordinates, distinguish the manufactured regions. Their
         * coincident spatial placement is intentional and not a physical mesh.
         */
        mesh->ipkon[element] = 4 * element;
        mesh->ipkon[element + 1] = 4 * (element + 1);
        memcpy(&mesh->lakon[8 * element], "C3D4    ", 8);
        memcpy(&mesh->lakon[8 * (element + 1)], "C3D4    ", 8);
        for (node = 0; node < 3; node++) {
            mesh->kon[4 * element + node] = base + node + 1;
            mesh->kon[4 * (element + 1) + node] = base + node + 1;
        }
        mesh->kon[4 * element + 3] = base + 4;
        mesh->kon[4 * (element + 1) + 3] = base + 5;
        memcpy(&mesh->coordinates[3 * base], positions, sizeof(positions));
    }
    for (node = 0; node < mesh->nk; node++) {
        for (dir = 1; dir <= 3; dir++) {
            mesh->active[UNIT_MT * node + dir] = active++;
        }
    }
}

static void release_mesh(UnitMesh* mesh)
{
    ITG index;
    for (index = 0; index < fa.nb; index++) {
        free(fa.bodies[index].elements);
        free(fa.bodies[index].cut);
    }
    for (index = 0; index < fa.nss; index++) {
        free(fa.spc_supports[index].nodes);
        free(fa.spc_supports[index].directions);
    }
    free(fa.supports); free(fa.spc_supports); free(fa.bodies);
    free(fa.ports); free(fa.angles); free(fa.springs);
    free(fa.owners); free(fa.node_union); free(fa.node_intersection);
    free(fa.faces); free(fa.points); free(fa.loads);
    free(fa.contacts); free(fa.contact_owners);
    free(fa.structural_nodes); free(fa.original_co);
    memset(&fa, 0, sizeof(fa));
    free(mesh->ipkon); free(mesh->kon); free(mesh->lakon);
    free(mesh->coordinates); free(mesh->active); free(mesh->internal);
    free(mesh->external); free(mesh->displacement);
    memset(mesh, 0, sizeof(*mesh));
}

static void prepare_bodies(UnitMesh* mesh, ITG version, const char* path)
{
    ITG region, perturb[2] = {0, 0};
    FILE* request = create_new_request(path);
    fprintf(request, "CCX_FORCE_ACCOUNTING_V%d\n", version);
    for (region = 0; region < mesh->regions; region++) {
        fprintf(request, "BODY ArtificialBody%d 1 3\n%d\n%d %d %d\n",
                region, 2 * region + 1, 5 * region + 1,
                5 * region + 2, 5 * region + 3);
    }
    fprintf(request, "END\n");
    check(fclose(request) == 0, "cannot close artificial body request");
    check(setenv("CCX_FORCE_ACCOUNTING_REQUEST", path, 1) == 0,
          "cannot set unit-owned request path");
    fa_prepare(1, perturb, 0, 0, 0, 1, mesh->nk, mesh->ne,
               mesh->coordinates, mesh->ipkon, mesh->kon, mesh->lakon,
               0, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, 0);
    check(fa.nb == mesh->regions, "actual body parser did not retain all declarations");
    check(fa.owner_words == (version == 3 ? UNIT_WORDS : 1),
          "actual ownership row width differs from the case's literal width");
}

static const uint64_t* literal_mask(ITG body)
{
    static const uint64_t zero[UNIT_WORDS] = {1, 0, 0, 0, 0};
    static const uint64_t sixty_three[UNIT_WORDS] = {UINT64_C(0x8000000000000000), 0, 0, 0, 0};
    static const uint64_t sixty_four[UNIT_WORDS] = {0, 1, 0, 0, 0};
    static const uint64_t one_twenty_seven[UNIT_WORDS] = {0, UINT64_C(0x8000000000000000), 0, 0, 0};
    static const uint64_t one_twenty_eight[UNIT_WORDS] = {0, 0, 1, 0, 0};
    static const uint64_t two_sixty_three[UNIT_WORDS] = {0, 0, 0, 0, 128};
    switch (body) {
        case 0: return zero;
        case 63: return sixty_three;
        case 64: return sixty_four;
        case 127: return one_twenty_seven;
        case 128: return one_twenty_eight;
        case 263: return two_sixty_three;
        default: unit_fail("no independently declared literal mask for this target");
    }
    return NULL;
}

static void check_words(const uint64_t* row, ITG body)
{
    size_t word;
    const uint64_t* reference = literal_mask(body);
    for (word = 0; word < fa.owner_words; word++) {
        check(row[word] == reference[word], "raw owner words differ from fixed literal mask");
    }
}

static void check_ownership(UnitMesh* mesh)
{
    ITG region, candidate, shared;
    size_t word;
    static const ITG targets[] = {0, 63, 64, 127, 128, 263};
    size_t target;
    /* This exhaustive membership check complements, but does not replace, the
     * raw literal word checks below. It cannot hide a mirrored add/has bug.
     */
    for (region = 0; region < mesh->regions; region++) {
        ITG owned = 2 * region, apex = 5 * region + 3;
        for (candidate = 0; candidate < mesh->regions; candidate++) {
            int same_region = candidate == region;
            check(owner_has(fa.owners, owned, candidate) == same_region,
                  "owned element identity aliases another declaration");
            check(!owner_has(fa.owners, owned + 1, candidate),
                  "unowned element acquired a declaration");
            check(owner_has(fa.node_union, apex, candidate) == same_region &&
                  owner_has(fa.node_intersection, apex, candidate) == same_region,
                  "exclusive node union/intersection differs from region membership");
            for (shared = 0; shared < 3; shared++) {
                check(owner_has(fa.node_union, 5 * region + shared, candidate) == same_region,
                      "shared node union differs from region membership");
                check(!owner_has(fa.node_intersection, 5 * region + shared, candidate),
                      "shared node intersection retained an unowned incident element");
            }
            check(!owner_has(fa.node_union, apex + 1, candidate) &&
                  !owner_has(fa.node_intersection, apex + 1, candidate),
                  "unowned apex acquired an owner");
        }
    }
    for (target = 0; target < sizeof(targets) / sizeof(targets[0]); target++) {
        region = targets[target];
        if (region >= mesh->regions) {
            continue;
        }
        check_words(&fa.owners[2 * (size_t)region * fa.owner_words], region);
        check_words(&fa.node_union[5 * (size_t)region * fa.owner_words], region);
        check_words(&fa.node_intersection[(5 * (size_t)region + 3) * fa.owner_words], region);
        for (word = 0; word < fa.owner_words; word++) {
            check(fa.node_intersection[5 * (size_t)region * fa.owner_words + word] == 0,
                  "raw shared-node intersection is not empty");
        }
    }
}

static void load_point(ITG body, double force)
{
    ITG nodes[2] = {5 * body + 4, 0}, direction = 1;
    fa_pointloads(1, nodes, &direction, &force);
}

static void load_element(ITG body, double x, double y, double z)
{
    ITG element = 2 * body + 1, count = 4;
    ITG nodes[4] = {5 * body + 1, 5 * body + 2, 5 * body + 3, 5 * body + 4};
    double force[12] = {0};
    force[9] = x; force[10] = y; force[11] = z;
    FORTRAN(fa_elementload, (&element, &count, nodes, force));
}

static void manufacture_contact(ITG contact_element, ITG left, ITG right,
                                double x, double y, double z)
{
    ITG count = 6;
    ITG nodes[6] = {5 * left + 1, 5 * left + 2, 5 * left + 4,
                    5 * right + 1, 5 * right + 2, 5 * right + 4};
    double fnl[18] = {0};
    char label[8] = {'E', 'S', 'P', 'R', 'N', 'G', 'C', '3'};
    /* fa_contact's documented input sign is opposite its accounted force.
     * Apply only at each side's apex, whose coordinate is exactly (2,3,5).
     */
    fnl[6] = -x; fnl[7] = -y; fnl[8] = -z;
    fnl[15] = x; fnl[16] = y; fnl[17] = z;
    FORTRAN(fa_contact, (&contact_element, &count, nodes, fnl, label));
    check_words(&fa.contact_owners[2 * (size_t)(contact_element - 1) * fa.owner_words], left);
    check_words(&fa.contact_owners[(2 * (size_t)(contact_element - 1) + 1) * fa.owner_words], right);
}

static void literal_wrench(ITG body, int kind, const double values[6])
{
    memcpy(expected[body][kind], values, 6 * sizeof(double));
}

static void expected_multiword(void)
{
    static const double cut0[6] = {5, 0, 0, 0, 25, -15};
    static const double contact0[6] = {-5, 0, 0, 0, -25, 15};
    static const double load63[6] = {2, 0, 0, 0, 10, -6};
    static const double contact63[6] = {0, 0, 2, 6, -4, 0};
    static const double cut63[6] = {-2, 0, -2, -6, -6, 6};
    static const double load64[6] = {3, 4, 0, -20, 15, -1};
    static const double contact64[6] = {0, 0, -2, -6, 4, 0};
    static const double cut64[6] = {-3, -4, 2, 26, -19, 1};
    static const double load127[6] = {5, 0, 0, 0, 25, -15};
    static const double contact127[6] = {0, 3, 0, -15, 0, 6};
    static const double cut127[6] = {-5, -3, 0, 15, -25, 9};
    static const double load128[6] = {7, 0, 6, 18, 23, -21};
    static const double contact128[6] = {0, -3, 0, 15, 0, -6};
    static const double cut128[6] = {-7, 3, -6, -33, -23, 27};
    static const double load263[6] = {11, 0, 0, 0, 55, -33};
    static const double contact263[6] = {5, 0, 0, 0, 25, -15};
    static const double cut263[6] = {-16, 0, 0, 0, -80, 48};
    literal_wrench(0, UNIT_CUT, cut0); literal_wrench(0, UNIT_CONTACT, contact0);
    literal_wrench(63, UNIT_LOAD, load63); literal_wrench(63, UNIT_CONTACT, contact63);
    literal_wrench(63, UNIT_CUT, cut63);
    literal_wrench(64, UNIT_LOAD, load64); literal_wrench(64, UNIT_CONTACT, contact64);
    literal_wrench(64, UNIT_CUT, cut64);
    literal_wrench(127, UNIT_LOAD, load127); literal_wrench(127, UNIT_CONTACT, contact127);
    literal_wrench(127, UNIT_CUT, cut127);
    literal_wrench(128, UNIT_LOAD, load128); literal_wrench(128, UNIT_CONTACT, contact128);
    literal_wrench(128, UNIT_CUT, cut128);
    literal_wrench(263, UNIT_LOAD, load263); literal_wrench(263, UNIT_CONTACT, contact263);
    literal_wrench(263, UNIT_CUT, cut263);
}

static void verify_body_output(const char* path, ITG regions, ITG version)
{
    char* output_path = allocate(strlen(path) + 5, 1);
    char line[1024], envelope[81], kind[81], name[81], trailing;
    unsigned char seen[UNIT_BODIES][UNIT_KINDS] = {{0}};
    ITG body, component, rows = 0, ended = 0;
    int channel, row_body;
    double values[6];
    FILE* output;
    sprintf(output_path, "%s.out", path);
    output = fopen(output_path, "r");
    check(output != NULL, "missing actual fa_emit output");
    snprintf(envelope, sizeof(envelope), "CCX_FORCE_ACCOUNTING_V%d\n", version);
    check(fgets(line, sizeof(line), output) && !strcmp(line, envelope),
          "incorrect actual fa_emit version envelope");
    check(fgets(line, sizeof(line), output) && !strcmp(line, "STATE 1 1 1\n"),
          "incorrect actual fa_emit state");
    while (fgets(line, sizeof(line), output)) {
        if (!strcmp(line, "END\n")) {
            ended++;
            break;
        }
        check(sscanf(line, "%80s %80s %lf %lf %lf %lf %lf %lf %c", kind, name,
                     &values[0], &values[1], &values[2], &values[3], &values[4], &values[5],
                     &trailing) == 8, "malformed actual fa_emit body row");
        check(sscanf(name, "ArtificialBody%d%c", &row_body, &trailing) == 1 &&
              row_body >= 0 && row_body < regions, "unexpected emitted body identity");
        if (!strcmp(kind, "CUT")) channel = UNIT_CUT;
        else if (!strcmp(kind, "LOAD")) channel = UNIT_LOAD;
        else if (!strcmp(kind, "CONTACT")) channel = UNIT_CONTACT;
        else if (!strcmp(kind, "MPC") && version >= 2) channel = UNIT_MPC;
        else { unit_fail("unexpected emitted body channel"); return; }
        check(!seen[row_body][channel], "duplicate actual fa_emit body channel");
        seen[row_body][channel] = 1;
        rows++;
        for (component = 0; component < 6; component++) {
            check(isfinite(values[component]) && values[component] == expected[row_body][channel][component],
                  "actual emitted body wrench differs from fixed literal reference");
        }
    }
    check(ended == 1 && fgets(line, sizeof(line), output) == NULL,
          "missing END or trailing actual fa_emit output");
    check(fclose(output) == 0, "cannot close actual fa_emit output");
    check(rows == regions * (version == 1 ? 3 : 4), "incomplete emitted body-channel table");
    for (body = 0; body < regions; body++) {
        for (channel = 0; channel < (version == 1 ? 3 : 4); channel++) {
            check(seen[body][channel], "an original body declaration lost an output channel");
        }
    }
    free(output_path);
}

static void run_body_case(const char* path, ITG version)
{
    UnitMesh mesh;
    size_t index;
    make_mesh(&mesh, version == 3 ? UNIT_BODIES : 64);
    prepare_bodies(&mesh, version, path);
    check_ownership(&mesh);
    fa_begin_results(mesh.ne + (version == 3 ? 3 : 1), mesh.ipkon, mesh.kon,
                     mesh.lakon, mesh.coordinates);
    if (version == 3) {
        check(fa.declarations == 264, "V3 applied count lost a BODY declaration");
        expected_multiword();
        load_point(63, 2); load_point(64, 3); load_point(127, 5);
        load_point(128, 7); load_point(263, 11);
        load_element(64, 0, 4, 0); load_element(128, 0, 0, 6);
        manufacture_contact(mesh.ne + 1, 63, 64, 0, 0, 2);
        manufacture_contact(mesh.ne + 2, 127, 128, 0, 3, 0);
        manufacture_contact(mesh.ne + 3, 263, 0, 5, 0, 0);
    } else {
        static const double load63[6] = {2, 0, 0, 0, 10, -6};
        static const double contact63[6] = {0, 0, 2, 6, -4, 0};
        static const double cut63[6] = {-2, 0, -2, -6, -6, 6};
        static const double contact0[6] = {0, 0, -2, -6, 4, 0};
        static const double cut0[6] = {0, 0, 2, 6, -4, 0};
        literal_wrench(63, UNIT_LOAD, load63); literal_wrench(63, UNIT_CONTACT, contact63);
        literal_wrench(63, UNIT_CUT, cut63);
        literal_wrench(0, UNIT_CONTACT, contact0); literal_wrench(0, UNIT_CUT, cut0);
        load_point(63, 2);
        manufacture_contact(mesh.ne + 1, 63, 0, 0, 0, 2);
    }
    fa_emit(mesh.internal, mesh.external, mesh.nk, UNIT_MT, mesh.active, 0,
            NULL, NULL, NULL, mesh.displacement, 1, 1, 1);
    verify_body_output(path, mesh.regions, version);
    fa_reset_loads();
    for (index = 0; index < 6 * (size_t)mesh.regions; index++) {
        check(fa.points[index] == 0, "actual load reset missed a dynamic body point slot");
    }
    for (index = 0; index < 6 * (size_t)mesh.ne; index++) {
        check(fa.loads[index] == 0, "actual load reset missed an element slot");
    }
    printf("{\"scope\":\"ARTIFICIAL_NATIVE_CAPACITY_MASK_UNIT_NOT_PHYSICAL_QUALIFICATION\","
           "\"case\":\"%s\",\"schema_version\":%d,\"bodies\":%d,\"owner_words\":%zu,"
           "\"actual_prepare_contact_point_reset_emit\":true,"
           "\"actual_element_callback\":%s,\"passed\":true}\n",
           version == 3 ? "multiword" : (version == 2 ? "legacy-v2" : "legacy-v1"),
           version, mesh.regions, fa.owner_words, version == 3 ? "true" : "false");
    release_mesh(&mesh);
}

static void run_zero_body_spc(const char* path)
{
    UnitMesh mesh;
    ITG perturb[2] = {0, 0}, node = 4, direction = 1;
    double zero = 0;
    char boundary_type = 'B';
    char* output_path;
    FILE *request, *output;
    char line[1024], trailing;
    double values[6];
    size_t index;
    static const double support[6] = {4, 0, 0, 0, 20, -12};
    make_mesh(&mesh, 1);
    request = create_new_request(path);
    fprintf(request, "CCX_FORCE_ACCOUNTING_V3\nSPC_SUPPORT ArtificialZeroBodySPC 1\n4 1\nEND\n");
    check(fclose(request) == 0, "cannot close artificial ordinary-support request");
    check(setenv("CCX_FORCE_ACCOUNTING_REQUEST", path, 1) == 0,
          "cannot set unit-owned ordinary-support path");
    fa_prepare(1, perturb, 0, 0, 0, 1, mesh.nk, mesh.ne, mesh.coordinates,
               mesh.ipkon, mesh.kon, mesh.lakon, 1, &node, &direction, &zero,
               NULL, &boundary_type, 0, NULL, NULL, 0);
    check(fa.nb == 0 && fa.nss == 1 && fa.owner_words == 1 && fa.declarations == 1,
          "zero-body ordinary support did not retain its one-word empty-owner domain");
    for (index = 0; index < (size_t)mesh.nk; index++) {
        check(!owner_any(fa.node_union, index), "zero-body support acquired a body owner");
    }
    mesh.active[UNIT_MT * (node - 1) + direction] = -2;
    mesh.internal[UNIT_MT * (node - 1) + direction] = 4;
    fa_begin_results(mesh.ne, mesh.ipkon, mesh.kon, mesh.lakon, mesh.coordinates);
    fa_emit(mesh.internal, mesh.external, mesh.nk, UNIT_MT, mesh.active, 0,
            NULL, NULL, NULL, mesh.displacement, 1, 1, 1);
    output_path = allocate(strlen(path) + 5, 1);
    sprintf(output_path, "%s.out", path);
    output = fopen(output_path, "r");
    check(output != NULL, "missing zero-body actual fa_emit output");
    check(fgets(line, sizeof(line), output) && !strcmp(line, "CCX_FORCE_ACCOUNTING_V3\n"),
          "zero-body output has incorrect envelope");
    check(fgets(line, sizeof(line), output) && !strcmp(line, "STATE 1 1 1\n"),
          "zero-body output has incorrect state");
    check(fgets(line, sizeof(line), output) &&
          sscanf(line, "SUPPORT ArtificialZeroBodySPC %lf %lf %lf %lf %lf %lf %c",
                 &values[0], &values[1], &values[2], &values[3], &values[4], &values[5],
                 &trailing) == 6, "zero-body output has missing or malformed support");
    for (index = 0; index < 6; index++) {
        check(isfinite(values[index]) && values[index] == support[index],
              "zero-body support differs from fixed literal wrench");
    }
    check(fgets(line, sizeof(line), output) && !strcmp(line, "END\n") &&
          fgets(line, sizeof(line), output) == NULL, "unexpected zero-body output rows");
    check(fclose(output) == 0, "cannot close zero-body output");
    free(output_path);
    /* allocate(0,...) intentionally owns one dummy slot; zero BODY reset must
     * not write it, while the actual element-load array is reset completely.
     */
    fa.points[0] = 123;
    for (index = 0; index < 6 * (size_t)mesh.ne; index++) fa.loads[index] = 7;
    fa_reset_loads();
    check(fa.points[0] == 123, "zero-body reset wrote beyond its zero logical length");
    for (index = 0; index < 6 * (size_t)mesh.ne; index++) {
        check(fa.loads[index] == 0, "zero-body reset missed an element load slot");
    }
    printf("{\"scope\":\"ARTIFICIAL_NATIVE_CAPACITY_MASK_UNIT_NOT_PHYSICAL_QUALIFICATION\","
           "\"case\":\"zero-body-spc\",\"bodies\":0,\"supports\":1,\"owner_words\":1,"
           "\"actual_prepare_reset_emit\":true,\"passed\":true}\n");
    release_mesh(&mesh);
}

int main(int argc, char** argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: NativeCapacityMaskUnit CASE NEW_PRIVATE_REQUEST_PATH\n"
                        "cases: multiword legacy-v1 legacy-v2 zero-body-spc\n");
        return 2;
    }
    if (!strcmp(argv[1], "multiword")) run_body_case(argv[2], 3);
    else if (!strcmp(argv[1], "legacy-v1")) run_body_case(argv[2], 1);
    else if (!strcmp(argv[1], "legacy-v2")) run_body_case(argv[2], 2);
    else if (!strcmp(argv[1], "zero-body-spc")) run_zero_body_spc(argv[2]);
    else unit_fail("unknown artificial capacity/mask case");
    return 0;
}
