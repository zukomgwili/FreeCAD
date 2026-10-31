/* SPDX-License-Identifier: GPL-2.0-only
 * Opt-in observation of native, unaveraged B32R end-section integrations.
 * The observer neither evaluates stresses/quadrature nor modifies mechanics,
 * native result arrays, output selections, convergence or ordinary files.
 */
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "CalculiX.h"

_Static_assert(sizeof(ITG) == sizeof(int), "Beam observation requires 32-bit native integers");

typedef struct
{
    ITG nodes[3];
    int declared;
} BSElement;

typedef struct
{
    ITG element, node, end;
    int seen, points;
    double position[3], e1[3], e2[3], normal[3];
    double force[3], moment[3], channels[6];
} BSSample;

typedef struct
{
    ITG step, increment, dataset;
    double time;
    BSSample* samples;
} BSFrame;

static struct
{
    int active, capturing, mapping, mapped, pending;
    ITG ne, step, increment;
    size_t count, frame_count;
    char* path;
    char request[33];
    double end_time, time;
    BSElement* elements;
    BSSample* samples;
    BSSample* current;
    BSFrame* frames;
} bs;

static void bs_fail(const char* message)
{
    fprintf(stderr, "*ERROR CCX beam section V1: %s\n", message);
    fflush(stderr);
    exit(201);
}

static size_t bs_product(size_t left, size_t right)
{
    if (right && left > SIZE_MAX / right) {
        bs_fail("allocation dimension overflow");
    }
    return left * right;
}

static void* bs_allocate(size_t count, size_t size)
{
    void* result;
    bs_product(count, size);
    result = calloc(count ? count : 1, size);
    if (!result) {
        bs_fail("allocation failed");
    }
    return result;
}

static void bs_token(FILE* stream, char token[81])
{
    if (fscanf(stream, "%80s", token) != 1) {
        bs_fail("truncated request");
    }
}

static void bs_expect(FILE* stream, const char* wanted)
{
    char token[81];
    bs_token(stream, token);
    if (strcmp(token, wanted)) {
        bs_fail("unexpected request token");
    }
}

static ITG bs_integer(FILE* stream)
{
    char token[81];
    const unsigned char* p;
    unsigned long value = 0;
    bs_token(stream, token);
    if (*token < '1' || *token > '9') {
        bs_fail("node and element labels require canonical positive integers");
    }
    for (p = (const unsigned char*)token; *p; ++p) {
        if (*p < '0' || *p > '9' ||
            value > ((unsigned long)INT_MAX - (unsigned long)(*p - '0')) / 10) {
            bs_fail("node or element label overflow");
        }
        value = 10 * value + (unsigned long)(*p - '0');
    }
    return (ITG)value;
}

static char* bs_suffix(const char* suffix)
{
    size_t path_length = strlen(bs.path), suffix_length = strlen(suffix);
    char* result;
    if (path_length > SIZE_MAX - suffix_length - 1) {
        bs_fail("output path overflow");
    }
    result = bs_allocate(path_length + suffix_length + 1, 1);
    memcpy(result, bs.path, path_length);
    memcpy(result + path_length, suffix, suffix_length + 1);
    return result;
}

static void bs_absent(const char* path)
{
    struct stat info;
    errno = 0;
    if (!lstat(path, &info) || errno != ENOENT) {
        bs_fail("output and temporary paths must be fresh for this child");
    }
}

static void bs_finish(void)
{
    if (bs.active && (!bs.frame_count || bs.pending ||
                      bs.frames[bs.frame_count - 1].time != bs.end_time)) {
        fprintf(stderr, "*ERROR CCX beam section V1: missing complete final native frame\n");
        fflush(NULL);
        _Exit(201);
    }
}

void bs_prepare(ITG method, ITG* perturb, ITG thermal, ITG transforms,
                ITG cyclic, ITG step, ITG nk, ITG ne, ITG nkon,
                ITG* ipkon, ITG* kon, char* lakon, char* filab)
{
    const char* path = getenv("CCX_BEAM_SECTION_REQUEST");
    FILE* stream;
    char token[81], *tail, *output, *temporary;
    struct stat info;
    ITG element, node, k, index;
    int byte;
    size_t count = 0, i;
    if (!path) {
        return;
    }
    if (!*path || bs.active || strlen(path) > 4096) {
        bs_fail("requires a nonempty request path and one standalone step");
    }
    if (method != 1 || perturb[1] || thermal > 1 || transforms || cyclic || step != 1) {
        bs_fail("requires one small-displacement global mechanical static step");
    }
    if (nk < 1 || ne < 1 || nkon < 23 ||
        strncmp(filab + 174, "S   ", 4) || filab[178] != 'M' || filab[179] == 'L') {
        bs_fail("requires native B32R SECTION FORCES with global source stresses");
    }
    if (lstat(path, &info) || !S_ISREG(info.st_mode)) {
        bs_fail("request must be a regular non-symlink file");
    }
    bs.path = bs_allocate(strlen(path) + 1, 1);
    strcpy(bs.path, path);
    output = bs_suffix(".out");
    temporary = bs_suffix(".out.tmp");
    bs_absent(output);
    bs_absent(temporary);
    free(output);
    free(temporary);
    bs.ne = ne;
    bs.elements = bs_allocate((size_t)ne, sizeof(BSElement));
    for (element = 0; element < ne; ++element) {
        if (ipkon[element] < 0) {
            continue;
        }
        if (strncmp(lakon + 8 * (size_t)element, "C3D20RB", 7) ||
            ipkon[element] > nkon - 23) {
            bs_fail("only active expanded B32R elements are supported");
        }
        ++count;
    }
    if (!count) {
        bs_fail("no active B32R elements");
    }
    stream = fopen(path, "r");
    if (!stream) {
        bs_fail("cannot read request");
    }
    while ((byte = fgetc(stream)) != EOF) {
        if (!byte || (byte < 32 && byte != '\n' && byte != '\r' && byte != '\t')) {
            bs_fail("request contains a non-text byte");
        }
    }
    if (ferror(stream) || fseek(stream, 0, SEEK_SET)) {
        bs_fail("cannot inspect or rewind request");
    }
    bs_expect(stream, "CCX_BEAM_SECTION_V1");
    bs_expect(stream, "REQUEST");
    bs_token(stream, token);
    if (strlen(token) != 32) {
        bs_fail("request identity must be 32 lowercase hexadecimal characters");
    }
    for (i = 0; i < 32; ++i) {
        if (!(token[i] >= '0' && token[i] <= '9') &&
            !(token[i] >= 'a' && token[i] <= 'f')) {
            bs_fail("request identity must be 32 lowercase hexadecimal characters");
        }
    }
    memcpy(bs.request, token, 33);
    bs_expect(stream, "END_TIME");
    bs_token(stream, token);
    errno = 0;
    bs.end_time = strtod(token, &tail);
    if (errno || *tail || !isfinite(bs.end_time) || bs.end_time <= 0.) {
        bs_fail("requires a finite positive requested end time");
    }
    bs_expect(stream, "UNITS");
    bs_expect(stream, "MM");
    bs_expect(stream, "N");
    bs_expect(stream, "NMM");
    for (;;) {
        bs_token(stream, token);
        if (!strcmp(token, "END")) {
            break;
        }
        if (strcmp(token, "ELEMENT")) {
            bs_fail("expected an ELEMENT record or END");
        }
        element = bs_integer(stream);
        if (element > ne || ipkon[element - 1] < 0 || bs.elements[element - 1].declared) {
            bs_fail("duplicate, inactive or unknown requested element");
        }
        index = ipkon[element - 1] + 20;
        for (k = 0; k < 3; ++k) {
            node = bs_integer(stream);
            if (node > nk || node != kon[index + k]) {
                bs_fail("requested B32R connectivity differs from the native expansion");
            }
            bs.elements[element - 1].nodes[k] = node;
        }
        if (bs.elements[element - 1].nodes[0] == bs.elements[element - 1].nodes[1] ||
            bs.elements[element - 1].nodes[0] == bs.elements[element - 1].nodes[2] ||
            bs.elements[element - 1].nodes[1] == bs.elements[element - 1].nodes[2]) {
            bs_fail("repeated nodes in requested beam");
        }
        bs.elements[element - 1].declared = 1;
        ++bs.count;
    }
    if (fscanf(stream, "%80s", token) != EOF || ferror(stream) || fclose(stream) ||
        bs.count != count) {
        bs_fail("request must declare the complete native B32R catalogue exactly once");
    }
    bs.samples = bs_allocate(bs_product((size_t)ne, 2), sizeof(BSSample));
    if (atexit(bs_finish)) {
        bs_fail("cannot register final-frame validation");
    }
    bs.active = 1;
}

void bs_begin_results(ITG iout, ITG step, ITG increment, double time)
{
    if (!bs.active) {
        return;
    }
    bs.capturing = 0;
    bs.mapping = 0;
    /* Linear static writes its retained final result with iout=1;
     * nonlinear retained evaluations use iout=2. Actual FRD binding below
     * is required in either case; a computed map alone is not a frame. */
    if (iout != 1 && iout != 2) {
        return;
    }
    if (bs.pending || bs.current || step != 1 || increment < 1 ||
        !isfinite(time) || time <= 0. || time > bs.end_time) {
        bs_fail("invalid or unconsumed retained native result evaluation");
    }
    memset(bs.samples, 0, bs_product(bs_product((size_t)bs.ne, 2), sizeof(BSSample)));
    bs.step = step;
    bs.increment = increment;
    bs.time = time;
    bs.mapped = 0;
    bs.pending = 1;
    bs.capturing = 1;
}

void FORTRAN(bs_map_begin, ())
{
    if (!bs.active || !bs.capturing) {
        return;
    }
    if (bs.mapping || bs.mapped) {
        bs_fail("duplicate native stress-section map");
    }
    bs.mapping = 1;
}

ITG FORTRAN(bs_mapping_active, ())
{
    return bs.active && bs.mapping;
}

static double bs_dot(const double* first, const double* second)
{
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2];
}

void FORTRAN(bs_end_begin, (ITG* element, ITG* node, ITG* end,
                            double* position, double* e1, double* e2, double* normal))
{
    BSSample* sample;
    size_t k, slot;
    if (!bs.active || !bs.mapping) {
        return;
    }
    if (bs.current || *element < 1 || *element > bs.ne ||
        (*end != 1 && *end != 3) || !bs.elements[*element - 1].declared) {
        bs_fail("invalid native beam/end observation");
    }
    slot = 2 * (size_t)(*element - 1) + (*end == 3);
    sample = bs.samples + slot;
    if (sample->seen || *node != bs.elements[*element - 1].nodes[*end - 1]) {
        bs_fail("duplicate end or mismatched native beam node");
    }
    sample->element = *element;
    sample->node = *node;
    sample->end = *end;
    for (k = 0; k < 3; ++k) {
        if (!isfinite(position[k]) || !isfinite(e1[k]) ||
            !isfinite(e2[k]) || !isfinite(normal[k])) {
            bs_fail("nonfinite native section centroid or projection axis");
        }
        sample->position[k] = position[k];
        sample->e1[k] = e1[k];
        sample->e2[k] = e2[k];
        sample->normal[k] = normal[k];
    }
    if (fabs(bs_dot(e1, e1) - 1.) > 1.e-8 || fabs(bs_dot(e2, e2) - 1.) > 1.e-8 ||
        fabs(bs_dot(normal, normal) - 1.) > 1.e-8 || fabs(bs_dot(e1, e2)) > 1.e-8 ||
        fabs(bs_dot(e1, normal)) > 1.e-8 || fabs(bs_dot(e2, normal)) > 1.e-8) {
        bs_fail("native section axes are not finite orthonormal projection directions");
    }
    bs.current = sample;
}

void FORTRAN(bs_end_point, (double* force_increment, double* moment_increment))
{
    BSSample* sample = bs.current;
    size_t k;
    if (!bs.active || !bs.mapping) {
        return;
    }
    if (!sample || sample->points == INT_MAX) {
        bs_fail("native section point outside an active end observation");
    }
    for (k = 0; k < 3; ++k) {
        if (!isfinite(force_increment[k]) || !isfinite(moment_increment[k])) {
            bs_fail("nonfinite native section force or moment increment");
        }
        sample->force[k] += force_increment[k];
        sample->moment[k] += moment_increment[k];
        if (!isfinite(sample->force[k]) || !isfinite(sample->moment[k])) {
            bs_fail("native section integral overflow");
        }
    }
    ++sample->points;
}

void FORTRAN(bs_end_finish, ())
{
    BSSample* sample = bs.current;
    size_t k;
    if (!bs.active || !bs.mapping) {
        return;
    }
    if (!sample || sample->points < 1) {
        bs_fail("empty native section integration");
    }
    sample->channels[0] = bs_dot(sample->e1, sample->force);
    sample->channels[1] = bs_dot(sample->e2, sample->force);
    sample->channels[2] = bs_dot(sample->normal, sample->force);
    sample->channels[3] = bs_dot(sample->normal, sample->moment);
    sample->channels[4] = bs_dot(sample->e2, sample->moment);
    sample->channels[5] = bs_dot(sample->e1, sample->moment);
    for (k = 0; k < 6; ++k) {
        if (!isfinite(sample->channels[k])) {
            bs_fail("nonfinite native local resultant projection");
        }
    }
    sample->seen = 1;
    bs.current = NULL;
}

void FORTRAN(bs_map_end, ())
{
    ITG element;
    size_t count = 0;
    if (!bs.active || !bs.capturing) {
        return;
    }
    if (!bs.mapping || bs.current) {
        bs_fail("incomplete native stress-section map");
    }
    for (element = 0; element < bs.ne; ++element) {
        if (bs.elements[element].declared) {
            if (!bs.samples[2 * (size_t)element].seen ||
                !bs.samples[2 * (size_t)element + 1].seen) {
                bs_fail("missing native B32R end observation");
            }
            count += 2;
        }
    }
    if (count != 2 * bs.count) {
        bs_fail("native sample catalogue mismatch");
    }
    bs.mapping = 0;
    bs.mapped = 1;
    bs.capturing = 0;
}

static void bs_vector(FILE* stream, const double* value)
{
    fprintf(stream, "[%.17g,%.17g,%.17g]", value[0], value[1], value[2]);
}

static void bs_write(void)
{
    char* output = bs_suffix(".out");
    char* temporary = bs_suffix(".out.tmp");
    FILE* stream = fopen(temporary, "wx");
    size_t frame, row;
    int bad;
    if (!stream) {
        bs_fail("cannot exclusively create native observer output");
    }
    fprintf(stream, "{\"schema\":\"CCX_BEAM_SECTION_V1\",\"request\":\"%s\","
            "\"complete\":%s,\"units\":{\"length\":\"mm\",\"force\":\"N\",\"moment\":\"N*mm\"},"
            "\"position_frame\":\"CURRENT_EXPANDED_SECTION\","
            "\"basis_frame\":\"NATIVE_CURRENT_FACE_BASIS\","
            "\"sample_identity_scope\":\"ELEMENT_END_BEFORE_NODE_AVERAGING\","
            "\"moment_reference\":\"NATIVE_SECTION_CENTROID\","
            "\"force_action\":\"OUTWARD_NATIVE_ELEMENT_END_FACE\","
            "\"native_channels_method\":\"PROJECTED_NATIVE_FORCE_AND_MOMENT_INCREMENT_SUM\","
            "\"completion_requires_successful_child\":true,\"frames\":[",
            bs.request, bs.frames[bs.frame_count - 1].time == bs.end_time ? "true" : "false");
    for (frame = 0; frame < bs.frame_count; ++frame) {
        BSFrame* item = bs.frames + frame;
        int first = 1;
        fprintf(stream, "%s{\"step\":%d,\"increment\":%d,\"frame\":%d,\"time\":%.17g,"
                "\"complete\":true,\"samples\":[", frame ? "," : "",
                item->step, item->increment, item->dataset, item->time);
        for (row = 0; row < 2 * (size_t)bs.ne; ++row) {
            BSSample* sample = item->samples + row;
            if (!sample->seen) {
                continue;
            }
            fprintf(stream, "%s{\"element\":%d,\"node\":%d,\"end\":%d,\"position\":",
                    first ? "" : ",", sample->element, sample->node, sample->end);
            first = 0;
            bs_vector(stream, sample->position);
            fprintf(stream, ",\"force_global\":");
            bs_vector(stream, sample->force);
            fprintf(stream, ",\"moment_global\":");
            bs_vector(stream, sample->moment);
            fprintf(stream, ",\"basis\":{\"e1\":");
            bs_vector(stream, sample->e1);
            fprintf(stream, ",\"e2\":");
            bs_vector(stream, sample->e2);
            fprintf(stream, ",\"normal\":");
            bs_vector(stream, sample->normal);
            fprintf(stream, "},\"native_channels\":{\"shear1\":%.17g,\"shear2\":%.17g,"
                    "\"axial\":%.17g,\"torque\":%.17g,\"bend2\":%.17g,\"bend1\":%.17g}}",
                    sample->channels[0], sample->channels[1], sample->channels[2],
                    sample->channels[3], sample->channels[4], sample->channels[5]);
        }
        fprintf(stream, "]}");
    }
    fprintf(stream, "]}\n");
    bad = ferror(stream);
    if (fclose(stream)) {
        bad = 1;
    }
    if (bad || rename(temporary, output)) {
        bs_fail("cannot atomically publish native observer output");
    }
    free(output);
    free(temporary);
}

void bs_frd_frame(ITG dataset, ITG step, ITG increment, double time)
{
    BSFrame* replacement;
    BSFrame* frame;
    if (!bs.active) {
        return;
    }
    if (!bs.pending || !bs.mapped || bs.mapping || bs.current || dataset < 1 ||
        step != bs.step || increment != bs.increment || time != bs.time) {
        bs_fail("FRD stress dataset differs from the observed native output evaluation");
    }
    if (bs.frame_count &&
        (dataset <= bs.frames[bs.frame_count - 1].dataset ||
         increment < bs.frames[bs.frame_count - 1].increment ||
         time < bs.frames[bs.frame_count - 1].time)) {
        bs_fail("nonmonotonic native FRD frame identity");
    }
    if (bs.frame_count == SIZE_MAX) {
        bs_fail("native frame count overflow");
    }
    replacement = realloc(bs.frames, bs_product(bs.frame_count + 1, sizeof(BSFrame)));
    if (!replacement) {
        bs_fail("native frame allocation failed");
    }
    bs.frames = replacement;
    frame = bs.frames + bs.frame_count++;
    frame->step = step;
    frame->increment = increment;
    frame->dataset = dataset;
    frame->time = time;
    frame->samples = bs_allocate(bs_product((size_t)bs.ne, 2), sizeof(BSSample));
    memcpy(frame->samples, bs.samples,
           bs_product(bs_product((size_t)bs.ne, 2), sizeof(BSSample)));
    bs.pending = 0;
    bs_write();
}
