#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int ITG;
#define FORTRAN(name,args) name args
/* Diagnostic input provenance for CalculiX's own *STEP default. The source
 * callbacks identify the table that steps.f synthesized, not a user table
 * with a similar name. Explicitly naming that generated table on any boundary
 * conservatively withdraws this exception. Mechanical arrays are untouched.
 */
static struct
{
    ITG generated;
    int explicitly_selected;
} step_default;
void FORTRAN(fa_generated_step, (ITG * amplitude))
{
    if (getenv("CCX_FORCE_ACCOUNTING_REQUEST")) {
        step_default.generated = *amplitude;
        step_default.explicitly_selected = 0;
    }
}
void FORTRAN(fa_explicit_amplitude, (ITG * amplitude))
{
    if (getenv("CCX_FORCE_ACCOUNTING_REQUEST") && *amplitude == step_default.generated) {
        step_default.explicitly_selected = 1;
    }
}
static ITG native_step_amplitude(
    ITG count, ITG points, const char* names, const ITG* tables, const double* values
)
{
    ITG amplitude = step_default.generated, first;
    size_t row, index;
    if (amplitude < 1 || amplitude > count || points < 2 || !names || !tables || !values ||
        step_default.explicitly_selected) {
        return 0;
    }
    row = (size_t)amplitude - 1;
    if (memcmp(&names[80 * row], "STEP12357111317", 15)) {
        return 0;
    }
    for (index = 15; index < 80; index++) {
        if (names[80 * row + index] != ' ') {
            return 0;
        }
    }
    first = tables[3 * row];
    if (first < 1 || first > points - 1 || tables[3 * row + 1] != first + 1 ||
        tables[3 * row + 2] != amplitude) {
        return 0;
    }
    index = 2 * ((size_t)first - 1);
    if (values[index] != 0. || values[index + 1] != 1. || values[index + 2] != 1.e20 ||
        values[index + 3] != 1.) {
        return 0;
    }
    return amplitude;
}
static int original_zero_spc(double value, ITG amplitude, char type, ITG generated_step)
{
    return isfinite(value) && value == 0. && type != 'R' &&
        (amplitude == 0 || (generated_step > 0 && amplitude == generated_step));
}

static int checks;
#define CHECK(condition) do { checks++; assert(condition); } while (0)
int main(void)
{
    ITG generated = 2, user = 1;
    char names[240];
    ITG tables[9] = {1,1,1, 2,3,2, 4,4,3};
    double values[8] = {0,0, 0,1, 1.e20,1, 0,1};
    memset(names, ' ', sizeof names);
    memcpy(&names[80], "STEP12357111317", 15);
    unsetenv("CCX_FORCE_ACCOUNTING_REQUEST");
    fa_generated_step(&generated);
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    CHECK(setenv("CCX_FORCE_ACCOUNTING_REQUEST","private-test-only",1)==0);
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    fa_generated_step(&generated);
    CHECK(native_step_amplitude(3,4,names,tables,values)==generated);
    CHECK(original_zero_spc(0,generated,'B',generated));
    CHECK(original_zero_spc(-0.,generated,'B',generated));
    CHECK(original_zero_spc(0,0,'B',0));
    CHECK(!original_zero_spc(0,user,'B',generated));
    CHECK(!original_zero_spc(0,3,'B',generated));
    CHECK(!original_zero_spc(0,-1,'B',generated));
    CHECK(!original_zero_spc(1.e-20,generated,'B',generated));
    CHECK(!original_zero_spc(-1.e-20,generated,'B',generated));
    CHECK(!original_zero_spc(NAN,generated,'B',generated));
    CHECK(!original_zero_spc(INFINITY,generated,'B',generated));
    CHECK(!original_zero_spc(-INFINITY,generated,'B',generated));
    CHECK(!original_zero_spc(0,generated,'R',generated));
    CHECK(!original_zero_spc(0,generated,'B',0));
    fa_explicit_amplitude(&user);
    CHECK(native_step_amplitude(3,4,names,tables,values)==generated);
    fa_explicit_amplitude(&generated);
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    CHECK(!original_zero_spc(0,generated,'B',native_step_amplitude(3,4,names,tables,values)));
    fa_generated_step(&generated);
    CHECK(native_step_amplitude(1,4,names,tables,values)==0);
    CHECK(native_step_amplitude(3,1,names,tables,values)==0);
    CHECK(native_step_amplitude(3,4,NULL,tables,values)==0);
    CHECK(native_step_amplitude(3,4,names,NULL,values)==0);
    CHECK(native_step_amplitude(3,4,names,tables,NULL)==0);
    names[80]='X';
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    names[80]='S'; names[95]='X';
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    names[95]=' ';
    for (int index=0; index<3; index++) {
        ITG save=tables[3+index];
        tables[3+index]=-1;
        CHECK(native_step_amplitude(3,4,names,tables,values)==0);
        tables[3+index]=save;
    }
    tables[3]=4;
    CHECK(native_step_amplitude(3,4,names,tables,values)==0);
    tables[3]=2;
    for (int index=2; index<6; index++) {
        double save=values[index];
        values[index]=NAN;
        CHECK(native_step_amplitude(3,4,names,tables,values)==0);
        values[index]=save;
        values[index]=save+3.;
        if (values[index]==save) values[index]=0.;
        CHECK(native_step_amplitude(3,4,names,tables,values)==0);
        values[index]=save;
    }
    CHECK(native_step_amplitude(3,4,names,tables,values)==generated);
    printf("SPC_GUARD_TEST PASS checks=%d\n",checks);
    return 0;
}
