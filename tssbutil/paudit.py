'''
tssbutil.paudit

Contains:
   class AuditParser
'''
import re
import sys
from tssbutil.tssbrun import *

class AuditParser(object):
    '''
    AuditParser parses the AUDIT.LOG from a TSSB run.  The resulting data
    is made accessible via a TSSBRun instance (and the tssbrun() accessor).
    The constructor may throw an exception if there is unexpected syntax
    in the file.
    '''

    def __init__(self, filename):
        '''
        Constructor.
        
        :param string filename: filename to parse
        '''
        self._filename = filename
        self._file = open(filename)
        self._lineno = 0
        self._tssbrun = TSSBRun()
        self.__last_line = None
        
        # set up patterns that designate different sections        
        self._selstatspatt = re.compile('^Selection statistics for model (\w+)$')
        self._wfstatspatt = re.compile('.*Walkforward is complete\.  Summary.*')
        self._wffoldspatt = re.compile('^Walkforward test date (\d+)')
        self._fgstatspatt = re.compile('^FIND GROUPS beginning')
        self._termpatt  = re.compile('# # # # # # # # # # # # # # # # # # # # # # #')                                      
        
        self.__parse()

    def tssbrun(self):        
        '''Returns the TSSBRun instance containing the parse results.'''
        return self._tssbrun
    
    def __parse(self):
        '''Top level parse method (PRIVATE).'''
        line = self.__get_line()
        while line != None:
            #print line
            res1 = self._selstatspatt.match(line)
            res2 = self._wfstatspatt.match(line)
            res3 = self._fgstatspatt.match(line)
            res4 = self._wffoldspatt.match(line)
            if res1:
                # TODO - decide whether this is best or just always initialize
                # in constructor
                if not self._tssbrun.selection_stats():
                    self._tssbrun.add_selection_stats(SelectionStats())
                self.__parse_selstats(res1)
            elif res2:
                self.__parse_wfstats()
            elif res3:
                self.__parse_wffold('FIND GROUPS')
            elif res4:
                self.__parse_wffold(res4.group(1))
                
            line = self.__get_line()
        
    def __parse_wffold(self,foldname):
        '''Parses a fold or the FIND GROUPS equivalent. (PRIVATE)'''
        fold = TSSBFold(foldname)
        
        groupstart = re.compile('^----------> Group (\d+)')
        modelstart = re.compile('^(Model|Committee) (\w+)')
        termpatt   = '**************************************************************'
        line = self.__get_line()        
        while line != None and not self._termpatt.match(line) and not line == termpatt:
            res1 = groupstart.match(line)
            res2 = modelstart.match(line)
            if res1:
                groupname = res1.group(1)
                modeliter = ModelIteration('Group', groupname)
                self.__parse_foldmodel(modeliter, hasOos = False)
                fold.add_model(modeliter)
            elif res2:
                modelname = res2.group(2)
                modeliter = ModelIteration(res2.group(1), modelname)
                self.__parse_foldmodel(modeliter)
                fold.add_model(modeliter)
                
            line = self.__get_line()
            
        self._tssbrun.add_fold(fold)

    def __parse_foldmodel(self,modeliter,hasOos = True):
        '''Parses a walk-forward or FIND GROUPS Model Iteration (PRIVATE).'''
        defn = ModelDefn()
        varmatch = re.compile('^\s*([-\.\d]+)\s+(\w+)\s*(.*)')
        oospatt  = re.compile('Out-of-sample results')
        pstate = 0
        line = self.__get_line()
        while line != None and not self._termpatt.match(line):
            # print 'line=%d,parse_foldmodel,state=%d,line=%s' % (self._lineno,pstate,line)
            if (pstate == 0 or pstate == 1) and varmatch.match(line):
                pstate = 1
                res = varmatch.match(line)
                defn.add_factor(res.group(2), float(res.group(1)), res.group(3))
            elif pstate == 1:
                # this is a case where the next stage may need this line
                self.__push_back(line)
                
                modeliter.set_defn(defn)
                pstate = 2
                res = self.__parse_std_result()
                modeliter.set_insample_stats(res)
                if not hasOos:
                    return
            elif pstate == 2 and oospatt.match(line):
                res = self.__parse_std_result()
                modeliter.set_oosample_stats(res)
                return

            line = self.__get_line()
        
    def __parse_std_result(self):
        '''Parses a standard results section (in- or out-of-sample) (PRIVATE).'''
        patt1 = re.compile('^Pooled out-of-sample.*')
        patt2 = re.compile('^\s*Target grand mean = ([-\.\d]+)')
        patt3a = re.compile('^(\d+) of (\d+) cases.*at or (.*) threshold(.*)')
        patt3b = re.compile('^Outer (hi|lo) thresh = ([-\.\d]+)\s+with (\d+) of (\d+) cases at or (above|below) \([-\.\d]+ %\)\s*(.*)')
        patt4 = re.compile('.*Mean = ([-\.\d]+)')
        patt5 = re.compile('.*ROC area = ([-\.\d]+)')
        patt6 = re.compile('^\s*Outer (long|short)\-only PF (.*)')
        patt6b = re.compile('\s*= ([-\.\d]+)\s*Improvement Ratio = ([-\.\d]+)')
        patt7 = re.compile('^Total profit\s+([-\.\d]+)\s+([-\.\d]+)\s+([-\.\d]+)\s+([-\.\d]+)')
        patt8 = re.compile('^.* (\w+) trades; total return = ([-\.\d]+)')
        patt9 = re.compile('^Max drawdown = (\d+\.\d+)')

        wfmstats = ModelStats()
        pstate = 1
        line = self.__get_line()
        while line != None:
            # print 'line=%d,parse_std_result,state=%d,line=%s' % (self._lineno,pstate,line)
            if pstate == 1 and patt1.match(line):
                # this means we are parsing a pooled out-of-sample section.  We parse the
                # next 3 rows that must contain the target grand mean and then above 
                # high and below low lines
                wfmstats.target_grand_mean = float(patt2.match(self.__get_line()).group(1))                
                mat1 = patt3a.match(self.__get_line())
                assert( mat1.group(3) == 'above outer high')
                wfmstats.num_above_high = int(mat1.group(1))
                wfmstats.total_cases = int(mat1.group(2))
                if wfmstats.num_above_high > 0:
                    mat2 = patt4.match(mat1.group(4)) 
                    wfmstats.mean_above_high = float(mat2.group(1))
                
                mat1 = patt3a.match(self.__get_line())
                assert( mat1.group(3) == 'below outer low')
                wfmstats.num_below_low = int(mat1.group(1))
                if wfmstats.num_below_low > 0:
                    mat2 = patt4.match(mat1.group(4)) 
                    wfmstats.mean_below_low = float(mat2.group(1))

                pstate = 2
            elif pstate == 1 and patt2.match(line):
                # this means we are parsing a pooled out-of-sample section.  We parse the
                # current 3 rows that must contain the target grand mean and then above 
                # high and below low lines
                wfmstats.target_grand_mean = float(patt2.match(line).group(1))                

                mat1 = patt3b.match(self.__get_line())
                assert mat1.group(1) == 'hi'
                wfmstats.num_above_high = int(mat1.group(3))
                wfmstats.total_cases = int(mat1.group(4))
                mat2 = patt4.match(mat1.group(6))
                if mat2:
                    wfmstats.mean_above_high = float(mat2.group(1))
                
                mat1 = patt3b.match(self.__get_line())
                assert mat1.group(1) == 'lo'
                wfmstats.num_below_low = int(mat1.group(3))
                mat2 = patt4.match(mat1.group(6))
                if mat2:
                    wfmstats.mean_below_low = float(mat2.group(1))

                pstate = 2
            elif pstate == 2 and patt5.match(line):
                # in pstate 2 we are looking for the line with ROC area
                mat = patt5.match(line)
                wfmstats.roc_area = float(mat.group(1))
                pstate = 3
            elif pstate == 3 and patt6.match(line):
                # in pstate 3 we are processing the long and short-only improvement
                mat1 = patt6.match(line) 
                assert(mat1.group(1) == 'long')
                if mat1.group(2).find('is infinite') != -1:
                    wfmstats.long_only_imp = float('Inf')
                elif mat1.group(2).find('is undefined') != -1:
                    wfmstats.long_only_imp = float('NaN')
                else:
                    mat2 = patt6b.match(mat1.group(2))
                    wfmstats.long_only_imp = float(mat2.group(2))

                mat1 = patt6.match(self.__get_line()) 
                assert(mat1.group(1) == 'short')
                if mat1.group(2).find('is infinite') != -1:
                    wfmstats.short_only_imp = float('Inf')
                elif mat1.group(2).find('is undefined') != -1:
                    wfmstats.short_only_imp = float('NaN')
                else:
                    mat2 = patt6b.match(mat1.group(2))
                    wfmstats.short_only_imp = float(mat2.group(2))
                pstate = 4
            elif pstate == 4 and patt7.match(line):
                # in pstate 4 we are looking for total return and maxdd if it exists
                # this case in for non pooled-oos when we have to take it from the
                # total profit line and have no max dd
                mat1 = patt7.match(line)
                
                wfmstats.long_total_ret = float(mat1.group(1))
                wfmstats.short_total_ret = float(mat1.group(4))
                return wfmstats
            elif pstate == 4 and patt8.match(line):
                # in pstate 4 we are looking for total return and maxdd if it exists
                # this is the pooled oos case where we get maxdd
                mat1 = patt8.match(line)
                assert(mat1.group(1) == 'long')
                wfmstats.long_total_ret = float(mat1.group(2))
                
                mat2 = patt9.match(self.__get_line())
                wfmstats.long_maxdd = float(mat2.group(1))

                line = self.__get_line()
                mat1 = patt8.match(line)
                assert(mat1.group(1) == 'short')
                wfmstats.short_total_ret = float(mat1.group(2))
                
                mat2 = patt9.match(self.__get_line())
                wfmstats.short_maxdd = float(mat2.group(1))
                return wfmstats

            line = self.__get_line()
        
    def __parse_wfstats(self):
        '''Parses the walk-forward summary section (PRIVATE).'''
        modelstart = re.compile('^(Model|Committee) (\w+).*')
        line = self.__get_line()
        while line != None and not self._termpatt.match(line):
            res1 = modelstart.match(line)
            if res1:
                modelname = res1.group(2)
                stats = self.__parse_std_result()
                self._tssbrun.add_pooled_summ(modelname, stats)
                
            line = self.__get_line()
    
    def __parse_selstats(self,mat):
        '''Parses variable selection stats for one model (PRIVATE).'''
        
        patt1 = re.compile('Variables selected...')
        patt2 = re.compile('Name   Percent')
        
        pstate = 0
        
        # the selection statistics section has two fixed lines we need to see 
        # before we start collecting variable names
        line = self.__get_line()
        while line != None and not self._termpatt.match(line):
            if pstate == 0 and patt1.match(line):
                pstate = 1
            elif pstate == 1 and patt2.match(line):
                pstate = 2
            elif pstate == 2:
                if line:
                    (variable, pct) = line.split()[0], line.split()[1]
                    self._tssbrun.selection_stats().add_model_variable(mat.group(1), variable, float(pct))
            line = self.__get_line()
        
    def __push_back(self, line):
        '''Put the last read line back to be read next (PRIVATE).'''
        self.__last_line = line

    def __get_line(self):
        '''Returns the next line to parse (PRIVATE).'''
        if self.__last_line:
            ret = self.__last_line
            self.__last_line = None
            return ret
        
        line = self._file.readline()
        if line:
            self._lineno = self._lineno + 1
            return line.strip()
        else:
            return None
        
if __name__ == '__main__':
    '''
    This is just a quick-and-dirty dump of the information that was 
    parsed.  It enables this Python module to be called directly with
    the name of the AUDIT.LOG to pass as a command-line arg.
    '''
    if len(sys.argv) < 2:
        print 'usage: paudit.py <AUDIT.LOG>'
        sys.exit(1)
        
    a = AuditParser(sys.argv[1])
    if a.tssbrun().selection_stats():
        print "Selection Statistics Summary:"
        for var in a.tssbrun().selection_stats().list_all_gt(3.0):
            print '%s,%0.2f%%' % (var[0],var[1])

    for (model,wfmstats) in a.tssbrun().walkforward_summ().iteritems():
        print 'Model %s walk-forward stats:' % model
        print wfmstats
        
    if a.tssbrun().folds()[0].name() == 'FIND GROUPS':
        fold = a.tssbrun().folds()[0]
        for (group,modeliter) in fold.models().iteritems():
            print 'Group %s find group stats:' % group
            for var in modeliter.defn().get_factors():
                print '    %12s: %0.5f' % (var[0],var[1])
            print modeliter.insample_stats()
            print '<<<<<>>>>>'
            
    sys.exit(0)