#!/usr/bin/env python2.5
"""
#############################################################################
##
## file :       threads.py
##
## description : see below
##
## project :     Tango Control System
##
## $Author: Sergi Rubio Manrique, srubio@cells.es $
##
## $Revision: 2011 $
##
## copyleft :    ALBA Synchrotron Controls Section, CELLS
##               Bellaterra
##               Spain
##
#############################################################################
##
## This file is part of Tango Control System
##
## Tango Control System is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as published
## by the Free Software Foundation; either version 3 of the License, or
## (at your option) any later version.
##
## Tango Control System is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
###########################################################################

by Sergi Rubio, 
srubio@cells.es, 
2010
"""
import time,Queue,threading,multiprocessing,traceback
import imp,__builtin__,pickle,re

from . import functional
from functional import *
from operator import isCallable
from objects import Singleton

try: from collections import namedtuple #Only available since python 2.6
except: pass

###############################################################################

class CronTab(object):
    """
    Line Syntax:
    #Minutes Hour DayOfMonth(1-31) Month(1-12) DayOfWeek(0=Sunday-6) Task
    00 */6 * * * /homelocal/sicilia/archiving/bin/cleanTdbFiles /tmp/archiving/tdb --no-prompt

    ct = fandango.threads.CronTab('* 11 24 08 3 ./command &') #command can be replaced by a callable task argument
    ct.match() #It will return True if actual time matches crontab condition, self.last_match stores last time check
        True
    ct.start()
        In CronTab(* 11 24 08 3 date).start()
        CronTab thread started

        In CronTab(* 11 24 08 3 date).do_task(<function <lambda> at 0x8cc4224>)
        CronTab(* 11 24 08 3 date).do_task() => 3
        
    ct.stop()

    """
    def __init__(self,line='',task=None,start=False,process=False,keep=10,trace=False):
        if line: self.load(line)
        if task is not None: self.task = task
        self.last_match = 0
        self.trace = trace
        self.keep = keep
        
        self.THREAD_CLASS = threading.Thread if not process else multiprocessing.Process
        self.QUEUE_CLASS = Queue.Queue if not process else multiprocessing.Queue
        self.EVENT_CLASS = threading.Event if not process else multiprocessing.Event
        self.LOCK_CLASS = threading.RLock if not process else multiprocessing.RLock

        self._thread = None
        self.event = None
        self._queue = self.QUEUE_CLASS(maxsize=int(self.keep or 10))
        if start: self.start()
        
    def load(self,line):
        """
        Crontab line parsing
        """
        print 'In CronTab().load(%s)'%line
        vals = line.split()
        if len(vals)<5: raise Exception('NotEnoughArguments')
        self.minute,self.hour,self.day,self.month,self.weekday = vals[:5]
        if vals[5:] or not getattr(self,'task',None): self.task = ' '.join(vals[5:])
        self.line = line
        
    def _check(self,cond,value):
        if '*'==cond: return True
        elif '*/' in cond: return not int(value)%int(cond.replace('*/',''))
        else: return int(cond)==int(value)
        
    def match(self,now=None):
        """
        Returns True if actual timestamp matches cron configuration
        """
        if now is None: now=time.time()
        self.last_match = now-(now%60)
        tt = functional.time2tuple(now)
        if all(self._check(c,v) for c,v in 
            zip([self.minute,self.hour,self.day,self.month,self.weekday],
                [tt.tm_min,tt.tm_hour,tt.tm_mday,tt.tm_mon,tt.tm_wday+1])
            ):
                return True
        else:
            return False
        
    def changed(self,now=None):
        """
        Checks if actual timestamp differs from last cron check
        """
        if now is None: now=time.time()
        return (now-(now%60))!=self.last_match
        
    def do_task(self,task=None,trace=False):
        """
        Executes an string or callable
        """
        trace = trace or self.trace
        task = task or self.task
        if trace: print 'In CronTab(%s).do_task(%s)'%(self.line,task)
        if functional.isCallable(task):
            ret = task()
        elif functional.isString(task):
            from fandango.linos import shell_command
            ret = shell_command(self.task)
        else:
            raise Exception('NotCallable/String')
        if self.keep:
            if self._queue.full(): self.get()
            self._queue.put(ret,False)
        if trace: 
            print 'CronTab(%s).do_task() => %s'%(self.line,ret)
            
    def get(self):
        return self._queue.get(False)
        
    def _run(self):
        print 'CronTab thread started' 
        from fandango.linos import shell_command
        while not self.event.is_set():
            now = time.time()
            if self.changed(now) and self.match(now):
                try:
                    self.do_task()
                except:
                    print 'CronTab thread exception' 
                    print traceback.format_exc()
            self.event.wait(15)
        print 'CronTab thread finished' 
        return 
        
    def start(self):
        print 'In CronTab(%s).start()'%self.line
        if self._thread and self._thread.is_alive:
            self.stop()
        import threading
        self._thread = self.THREAD_CLASS(target=self._run)
        self.event = self.EVENT_CLASS()
        self._thread.daemon = True
        self._thread.start()
        
    def stop(self):
        print 'In CronTab(%s).stop()'%self.line
        if self._thread and self._thread.is_alive:
            self.event.set()
            self._thread.join()
            
    def is_alive(self):
        if not self._thread: return False
        else: return self._thread.is_alive()
    
###############################################################################
WorkerException = type('WorkerException',(Exception,),{})

class WorkerThread(object):
    """
    This class allows to schedule tasks in a background thread or process
    
    The tasks introduced in the internal queue using put(Task) method may be:
         
         - dictionary of build_int types: {'__target__':callable or method_name,'__args__':[],'__class_':'','__module':'','__class_args__':[]}
         - string to eval: eval('import $MODULE' or '$VAR=code()' or 'code()')
         - list if list[0] is callable: value = list[0](*list[1:]) 
         - callable: value = callable()
            
    
    Usage::
        wt = fandango.threads.WorkerThread(process=True)
        wt.start()
        wt.put('import fandango')
        wt.put("tc = fandango.device.TangoCommand('lab/15/vgct-01/sendcommand')")
        command = "tc.execute(feedback='status',args=['ver\r\\n'])"
        wt.put("tc.execute(feedback='status',args=['ver\r\\n'])")
        while not wt.getDone():
            wt.stopEvent.wait(1.)
            pile = dict(wt.flush())
        result = pile[command]
    """
    
    SINGLETON = None
    
    def __init__(self,name='',process=False,wait=.01,target=None,singleton=False,trace=False):
        self._name = name
        self.wait = wait
        self._process = process
        self._trace = trace
        self.THREAD_CLASS = threading.Thread if not process else multiprocessing.Process
        self.QUEUE_CLASS = Queue.Queue if not process else multiprocessing.Queue
        self.EVENT_CLASS = threading.Event if not process else multiprocessing.Event
        self.LOCK_CLASS = threading.RLock if not process else multiprocessing.RLock

        self.inQueue = self.QUEUE_CLASS()
        self.outQueue = self.QUEUE_CLASS()
        self.errorQueue = self.QUEUE_CLASS()
        self.stopEvent = self.EVENT_CLASS()
        if target is not None: 
            self.put(target)
        
        self._thread = self.THREAD_CLASS(name='Worker',target=self.run)
        self._thread.daemon = True
            
        #if not singleton or WorkerThread.SINGLETON is None:
            #self._thread = self.THREAD_CLASS(name='Worker',target=self.run)
            #self._thread.daemon = True
        #if singleton:
            #if WorkerThread.SINGLETON is None:
                #WorkerThread.SINGLETON = self._thread
            #self._thread = WorkerThread.SINGLETON
                
        pass
    def __del__(self):
        try: 
            self.stop()
            object.__del__(self)
        except: pass
        
    def put(self,target):
        """
        Inserting a new object in the Queue.
        """
        self.inQueue.put(target,False)
    def get(self):
        """
        Getting the oldest element in the output queue in (command,result) format
        """
        try:
            self.getDone()
            try:
                while True: print self.errorQueue.get(False)
            except Queue.Empty: 
                pass
            return self.outQueue.get(False)
        except Queue.Empty: 
            #if self.outQueue.qsize():
                #print('FATAL PickleError, output queue has been lost')
                #self.outQueue = self.QUEUE_CLASS()
            return None
    def flush(self):
        """
        Getting all elements stored in the output queue in [(command,result)] format
        """
        result = []
        try:
            while True: result.append(self.outQueue.get(False))
        except Queue.Empty:
            pass
        return result
        
    def start(self):
        self._thread.start()
    def stop(self):
        self.stopEvent.set()
        self._thread.join()
    def isAlive(self):
        return self._thread.is_alive()
        
    def getQueue(self):
        return self.outQueue
    def getSize(self):
        return self.inQueue.qsize()
    def getDone(self):
        #self._pending-=self.outQueue.qsize()
        #if not self._done: return 0.
        #qs = self.inQueue.qsize()
        #return self._done/(self._done+qs) if qs else 1.
        return not self.inQueue.qsize() and not self.outQueue.qsize()
        
    def run(self):
        print 'WorkerThread(%s) started!'%self._name
        modules = {}
        instances = {}
        _locals = {}
        logger = getattr(__builtin__,'print') if not self._process else (lambda s:(getattr(__builtin__,'print')(s),self.errorQueue.put(s)))
        def get_module(_module):
            if module not in modules: 
                modules[module] = imp.load_module(*([module]+list(imp.find_module(module))))
            return modules[module]
        def get_instance(_module,_klass,_klass_args):
            if (_module,_klass,_klass_args) not in instances:
                instances[(_module,_klass,_klass_args)] = getattr(get_module(module),klass)(*klass_args)
            return instances[(_module,_klass,_klass_args)]
                
        while not self.stopEvent.is_set():
            try:
                target = self.inQueue.get(True,timeout=self.wait)
                if self.stopEvent.is_set(): break
                if target is None: continue
                try:
                    result = None
                    #f,args = objects.parseMappedFunction(target)
                    #if not f: raise WorkerException('targetMustBeCallable')
                    #else: self.outQueue.put(f())
                    if isDictionary(target):
                        model = target
                        keywords = ['__args__','__target__','__class__','__module__','__class_args__']
                        args = model['__args__'] if '__args__' in model else dict((k,v) for k,v in model.items() if k not in keywords)
                        target = model.get('__target__',None)
                        module = model.get('__module__',None)
                        klass = model.get('__class__',None)
                        klass_args = model.get('__class_args__',tuple())
                        if isCallable(target): 
                            target = model['__target__']
                        elif isString(target):
                            if module:
                                #module,subs = module.split('.',1)
                                if klass: 
                                    if self._trace: print('WorkerThread(%s) executing %s.%s(%s).%s(%s)'%(self._name,module,klass,klass_args,target,args))
                                    target = getattr(get_instance(module,klass,klass_args),target)
                                else:
                                    if self._trace: print('WorkerThread(%s) executing %s.%s(%s)'%(self._name,module,target,args))
                                    target = getattr(get_module(module),target)
                            elif klass and klass in dir(__builtin__):
                                if self._trace: print('WorkerThread(%s) executing %s(%s).%s(%s)'%(self._name,klass,klass_args,target,args))
                                instance = getattr(__builtin__,klass)(*klass_args)
                                target = getattr(instance,target)
                            elif target in dir(__builtin__): 
                                if self._trace: print('WorkerThread(%s) executing %s(%s)'%(self._name,target,args))
                                target = getattr(__builtin__,target)
                            else:
                                raise WorkerException('%s()_MethodNotFound'%target)
                        else:
                            raise WorkerException('%s()_NotCallable'%target)
                        value = target(**args) if isDictionary(args) else target(*args)
                        if self._trace: print('%s: %s'%(model,value))
                        self.outQueue.put((model,value))
                    else:
                        if isIterable(target) and isCallable(target[0]):
                            value = target[0](*target[1:])
                        elif isCallable(target):
                            value = target()
                        if isString(target):
                            if self._trace: print('eval(%s)'%target)
                            if target.startswith('import '): 
                                module = target.replace('import ','')
                                get_module(module)
                                value = module
                            elif (  '=' in target and 
                                    '='!=target.split('=',1)[1][0] and 
                                    re.match('[A-Za-z\._]+[A-Za-z0-9\._]+$',target.split('=',1)[0].strip())
                                ):
                                var = target.split('=',1)[0].strip()
                                _locals[var]=eval(target.split('=',1)[1].strip(),modules,_locals)
                                value = var
                            else:
                                value = eval(target,modules,_locals)
                                #try: 
                                    #pickle.dumps(value)
                                #except: 
                                    #print traceback.format_exc()
                                    #raise WorkerException('unpickableValue')
                        else:
                            raise WorkerException('targetMustBeCallable')
                        if self._trace: print('%s: %s'%(target,value))
                        try: pickle.dumps(value)
                        except pickle.PickleError: 
                            print traceback.format_exc()
                            raise WorkerException('UnpickableValue')
                        self.outQueue.put((target,value))
                except Exception,e:
                    msg = 'Exception in WorkerThread(%s).run()\n%s'%(self._name,traceback.format_exc())
                    print( msg)
                    self.outQueue.put((target,e))
                finally:
                    if not self._process: self.inQueue.task_done()
            except Queue.Empty:
                pass
            except:
                print 'FATAL Exception in WorkerThread(%s).run()'%self._name
                print traceback.format_exc()
        print 'WorkerThread(%s) finished!'%self._name
        
import objects

class SingletonWorker(WorkerThread,objects.Singleton):
    """
    Usage::
        # ... same like WorkerThread, but command is required to get the result value
        command = "tc.execute(feedback='status',args=['ver\r\\n'])"
        sw.put(command)
        sw.get(command)
    """
    def put(self,target):
        if not hasattr(self,'_queued'): self._queued = []
        self._queued.append(target)
        WorkerThread.put(self,target)
    def get(self,target):
        """
        It flushes the value stored for {target} task.
        The target argument is needed to avoid mixing up commands from different requestors.
        """
        if not hasattr(self,'_values'): self._values = {}
        self._values.update(WorkerThread.flush(self))
        [self._queued.remove(v) for v in self._values if v in self._queued]
        return self._values.pop(target)
        
    def getDone(self):
        return not bool(self._queued)
    def flush(self):
        l = []
        l.extend(getattr(self,'_values',{}).items())
        l.extend(WorkerThread.flush(self))
        if hasattr(self,'_queued'):
            while self._queued:
                self._queued.pop(0)
        return l

###############################################################################

class Pool(object):
    """ 
    It creates a queue of tasks managed by a pool of threads.
    Each task can be a Callable or a Tuple containing args for the "action" class argument.
    If "action" is not defined the first element of the tuple can be a callable, and the rest will be arguments
    
    Usage:
        p = Pool()
        for item in source(): p.add_task(item)
        p.start()
        while len(self.pending()):
            time.sleep(1.)
        print 'finished!'
    """
    
    def __init__(self,action=None,max_threads=5,start=False,mp=False):   
        import threading
        if mp==True:
            import multiprocessing
            self._myThread = multiprocessing.Process
            self._myQueue = multiprocessing.Queue
        else:
            import Queue
            self._myThread = threading.Thread
            self._myQueue = Queue.Queue
        self._action = action
        self._max_threads = max_threads
        self._threads = []
        self._pending = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._locked = partial(locked,_lock=self._lock)
        self._started = start
        self._queue = self._myQueue()
        
    def start(self):
        """ 
        Start all threads.
        """
        [t.start() for t in self._threads]
        self._started = True
        
    def stop(self):
        self._stop.set()
        [t.join(3.) for t in self._threads]
        #while not self._queue.empty(): self._queue.get()
        self._retire()
        self._started = False
        
    def add_task(self,item):#,block=False,timeout=None):
        """
        Adds a new task to the queue
        :param task: a callable or a tuple with callable and arguments
        """
        self._locked(self._pending.append,str(item))
        if self._started: self._retire()
        if len(self._pending)>len(self._threads) and len(self._threads)<self._max_threads:
            self._new_worker()        
        self._queue.put(item)#,block,timeout)

    def pending(self):
        """ returns a list of strings with the actions not finished yet"""
        self._retire()
        return self._pending
        
    ####################################################################################
    #Protected methods
            
    def _new_worker(self):
        #Creates a new thread
        t = self._myThread(target=self._worker)
        self._locked(self._threads.append,t)
        t.daemon = True
        if self._started: t.start()      
        
    def _retire(self):
        #Cleans dead threads
        dead = [t for t in self._threads if not t.is_alive()]
        for t in dead:
            self._locked(self._threads.remove,t) 
    
    def _worker(self):
        #Processing queue items
        while not self._stop.is_set() and not self._queue.empty():
            item = self._queue.get()
            try:
                if item is not None and isCallable(item): 
                    item()
                elif isSequence(item): 
                    if self._action: self._action(*item)
                    elif isCallable(item[0]): item[0](*item[1:])
                elif self._action: 
                    self._action(item)
            except:
                import traceback
                print('objects.Pool.worker(%s) failed: %s'%(str(item),traceback.format_exc()))
            self._remove_task(item)
        return
                
        
    def _remove_task(self,item=None):
        #Remove a finished task from the list
        if str(item) in self._pending: 
            self._locked(self._pending.remove,str(item))
        return getattr(self._queue,'task_done',lambda:None)()
            
    pass
    
###############################################################################
    
class AsynchronousFunction(threading.Thread):
    '''This class executes a given function in a separate thread
    When finished it sets True to self.finished, a threading.Event object 
    Whether the function is thread-safe or not is something that must be managed in the caller side.
    If you want to autoexecute the method with arguments just call: 
    t = AsynchronousFunction(lambda:your_function(args),start=True)
    while True:
        if not t.isAlive(): 
            if t.exception: raise t.exception
            result = t.result
            break
        print 'waiting ...'
        threading.Event().wait(0.1)
    print 'result = ',result
    '''
    def __init__(self,function):
        """It just creates the function object, you must call function.start() afterwards"""
        self.function  = function
        self.result = None
        self.exception = None
        self.finished = threading.Event()
        self.finished.clear()
        threading.Thread.__init__(self)
        self.wait = self.finished.wait
        self.daemon = False
    def run(self):
        try:
            self.wait(0.01)
            self.result = self.function()
        except Exception,e:
            self.result = None            
            self.exception = e
        self.finished.set() #Not really needed, simply call AsynchronousFunction.isAlive() to know if it has finished
