"""Extract the actual native admission predicates for a standalone C check.

This writes source only. Root compiles/runs it serially and retains the receipt.
The extracted code is byte-identical to the product source, without mocks of
CalculiX mechanics or a substitute solver. Whole-solver positives are separate.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/forceaccounting.c')
literal = SOURCE.read_text()
first = literal.index('/* Diagnostic input provenance for CalculiX\'s own *STEP default.')
last = literal.index('static void validate_spc_supports(', first)
body = literal[first:last]
header = '''#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int ITG;
#define FORTRAN(name,args) name args
'''
test = r'''
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
'''
output = ROOT / 'spc_guard_test.c'
output.write_text(header + body + test)
report = {
    'schema': 'FreeCAD-e4k-native-SPC-guard-test-recipe-v1',
    'product_source': str(SOURCE),
    'product_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'extracted_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
    'source_output': str(output),
    'source_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
    'compile_command': ['clang','-std=c11','-Wall','-Wextra','-Werror','-O2',str(output),'-o',str(ROOT/'spc_guard_test')],
    'run_command': [str(ROOT/'spc_guard_test')],
    'native_execution_by_this_writer': False,
    'scope': 'Actual extracted read-only default-table and original-zero-SPC admission predicates only; whole native solver/stock authoring qualification remains separate.',
}
(ROOT / 'spc-guard-test-recipe.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
