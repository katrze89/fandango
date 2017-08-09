#!/usr/bin/env python

#############################################################################
##
## project :     Tango Control System
##
## $Author: Sergi Rubio Manrique, srubio@cells.es $
##
## $Revision: 2008 $
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

"""
provides tango utilities for fandango, like database search methods and 
emulated Attribute Event/Value types

This module is a light-weight set of utilities for PyTango.
Classes dedicated for device management will go to fandango.device
Methods for Astor-like management will go to fandango.servers

.. contents::

.

"""

from .defaults import *
from .methods import *
from .search import *

###############################################################################
## Methods to export device/attributes/properties to dictionaries

AC_PARAMS = [
    'color',
    'display_unit',
    #'writable',
    'standard_unit',
    'quality',
    'unit',
    'string',
    'label',
    'min_alarm',
    'events',
    'description',
    #'data_type',
    'format',
    'max_alarm',
    #'device',
    #'name',
    #'database',
    #'data_format',
    #'value',
    #'polling',
    #'time',
    'alarms',
    #'model',
    #ALARMS
    'delta_t',
    'max_alarm',
    'min_warning',
    #'extensions',
    'delta_val',
    'min_alarm',
    'max_warning'
    #EVENTS
    #'extensions',
    'period',
    'archive_period',
    #'extensions',
    'archive_rel_change',
    'archive_abs_change',
    'rel_change',
    #'extensions',
    'abs_change',
    'per_event',
    'ch_event',
    'arch_event',
    ]


def export_attribute_to_dict(model,attribute=None,value=None,
                             keep=False,as_struct=False):
    """
    get attribute config, format and value from Tango and return it as a dict
    
    :param model: can be a full tango model, a device name or a device proxy
    
    keys: min_alarm,name,data_type,format,max_alarm,ch_event,data_format,value,
          label,writable,device,polling,alarms,arch_event,unit
    """
    attr,proxy = Struct(),None
    if not isString(model):
        model,proxy = model.name(),model
      
    model = parse_tango_model(model)
    attr.device = model['device']
    proxy = proxy or get_device(attr.device,keep=keep)
    attr.database = '%s:%s'%(model['host'],model['port'])
    attr.name = model.get('attribute',None) or attribute or 'state'
    attr.model = '/'.join((attr.database,attr.device,attr.name))
    attr.color = 'Lime'
    attr.time = 0
    attr.events = Struct()
    
    def vrepr(v):
      try: return str(attr.format)%(v)
      except: return str(v)
    def cleandict(d):
      for k,v in d.items():
        if v in ('Not specified','No %s'%k):
          d[k] = ''
      return d

    try:
        v = (value 
             or check_attribute(attr.database+'/'+attr.device+'/'+attr.name))

        if v and 'DevFailed' not in str(v):
            ac = proxy.get_attribute_config(attr.name)
            attr.description = (ac.description
                if ac.description!='No description' else '')
            
            attr.data_format = str(ac.data_format)
            attr.data_type = str(PyTango.CmdArgType.values[ac.data_type])
            attr.writable = str(ac.writable)
            attr.label,attr.min_alarm,attr.max_alarm = \
                ac.label,ac.min_alarm,ac.max_alarm
            attr.unit,attr.format = ac.unit,ac.format
            attr.standard_unit,attr.display_unit = \
                ac.standard_unit,ac.display_unit
            attr.events.ch_event = fandango.obj2dict(ac.events.ch_event)
            attr.events.arch_event = fandango.obj2dict(ac.events.arch_event)
            attr.events.per_event = fandango.obj2dict(ac.events.per_event)
            attr.alarms = fandango.obj2dict(ac.alarms)
            attr.quality = str(v.quality)
            attr.time = ctime2time(v.time)
              
            if attr.data_format!='SCALAR': 
                attr.value = list(v.value 
                    if v.value is not None and v.dim_x else [])
                sep = '\n' if attr.data_type == 'DevString' else ','
                svalue = map(vrepr,attr.value)
                attr.string = sep.join(svalue)
                if 'numpy' in str(type(v.value)): 
                  attr.value = map(fandango.str2type,svalue)
            else:
              if attr.data_type in ('DevState','DevBoolean'):
                  attr.value = int(v.value)
                  attr.string = str(v.value)
              else:
                  attr.value = v.value
                  attr.string = vrepr(v.value)
            if attr.unit.strip() not in ('','No unit'):
              attr.string += ' %s'%(attr.unit)
            attr.polling = proxy.get_attribute_poll_period(attr.name)
        else: 
            print((attr.device,attr.name,'unreadable!'))
            attr.value = None
            attr.string = str(v)
            
        if attr.value is None:
            attr.data_type = None
            attr.color = TANGO_STATE_COLORS['UNKNOWN']
        elif attr.data_type == 'DevState':
            attr.color = TANGO_STATE_COLORS.get(attr.string,'Grey')
        elif 'ALARM' in attr.quality:
            attr.color = TANGO_STATE_COLORS['FAULT']
        elif 'WARNING' in attr.quality:
            attr.color = TANGO_STATE_COLORS['ALARM']
        elif 'INVALID' in attr.quality:
            attr.color = TANGO_STATE_COLORS['OFF']
            
    except Exception,e:
        print(str((attr,traceback.format_exc())))
        raise(e)

    if as_struct:
        r = Struct(dict(attr))
    else:
        attr.events = dict(attr.events)
        r = dict(attr)
    return r
            
def export_commands_to_dict(device,target='*'):
    """ export all device commands config to a dictionary """
    name,proxy = ((device,get_device(device)) if isString(device) 
                  else (device.name(),device))
    dct = {}
    for c in proxy.command_list_query():
        if not fandango.matchCl(target,c.cmd_name): continue
        dct[c.cmd_name] = fandango.obj2dict(c)
        dct[c.cmd_name]['device'] = name
        dct[c.cmd_name]['name'] = c.cmd_name
    return dct
    
def export_properties_to_dict(device,target='*'):
    """ export device or class properties to dictionary """
    if '/' in device:
        return get_matching_device_properties(device,target)
    else:
        db = get_database()
        props = [p for p in db.get_class_property_list(device) 
                 if fandango.matchCl(target,p)]
        return dict((k,v if isString(v) else list(v)) for k,v in
                    db.get_class_property(device,props).items())
    
def export_device_to_dict(device,commands=True,properties=True):
    """
    This method can be used to export the current configuration of devices, 
    attributes and properties to a file.
    The dictionary will get properties, class properties, attributes, 
    commands, attribute config, event config, alarm config and pollings.
    
    .. code-block python:
    
        data = dict((d,fandango.tango.export_device_to_dict(d)) for d in fandango.tango.get_matching_devices('*00/*/*'))
        pickle.dump(data,open('bl00_devices.pck','w'))
        
    """
    i = get_device_info(device)
    dct = Struct(fandango.obj2dict(i,
            fltr=lambda n: n in 'dev_class host level name server'.split()))
    dct.attributes,dct.commands = {},{}
    if check_device(device):
      try:
        proxy = get_device(device)
        dct.attributes = dict((a,export_attribute_to_dict(proxy,a)) 
                              for a in proxy.get_attribute_list())
        if commands:
          dct.commands = export_commands_to_dict(proxy)
      except:
        traceback.print_exc()
    if properties:
      dct.properties = export_properties_to_dict(device)
      dct.class_properties = export_properties_to_dict(dct.dev_class)
    return dict(dct)

def import_device_from_dict(dct,device=None,server=None,create=True,
                            properties=True,attributes=True,events=True,
                            init=True,start=False,host=''):
    """
    This method will read a dictionary as generated by export_device_to_dict
    
    From the dictionary, properties for device and attributes will be applied
    
    properties,attributes,events can be boolean or regexp filter
    
    """
    name = device or dct['name']
    server = server or dct['server']
    if name not in get_all_devices():
        assert create,'Device %s does not exist!'%name  
        print('Creating %s at %s ...'%(name,server))
        add_new_device(server,dct['dev_class'],name)
    
    properties = '*' if properties is True else properties
    if properties:
        props = dict((k,v) for k,v in dct['properties'].items() 
                     if clmatch(properties,k))
        put_device_property(name,props)
        
    dp = get_device(name)
    if not attributes:
        return
    elif not check_device(dp):
        if not start:
            print('Device must be running to import attributes!')
            return
        from fandango import ServersDict
        print('Starting %s ...'%server)
        sd = ServersDict(name)
        sd.start_servers(host=host)
        time.sleep(5.)
    elif init:
        dp.init()

    if attributes is True:
        attributes = '*'
        
    attrs = dict((k,v) for k,v in dct['attributes'].items()
                 if clmatch(attributes,k))
    dp = get_device(name)
    alist = dp.get_attribute_list()
    alist = map(str.lower,alist)
    
    for a,v in attrs.items():
        if a.lower() not in alist:
            print('Attribute %s does not exist yet!'%a)
            continue
        
        if a.lower() not in ('state','status'):
            
            ac = dp.get_attribute_config(a)
            for c,vv in v.items():
                try:
                    if c not in AC_PARAMS:
                        continue                    
                    if c.lower() == 'events' and not events:
                        continue                
                    if not hasattr(ac,c):
                        continue
                    
                    #print('%s.%s.%s'%(name,a,c))
                    
                    if isinstance(vv,dict):
                        for cc,vvv in vv.items():
                            if cc not in AC_PARAMS:
                                continue
                            acc = getattr(ac,c)
                            if not hasattr(acc,cc):
                                continue
                            elif isinstance(vvv,dict):
                                for e,p in vvv.items():
                                    if e not in AC_PARAMS:
                                        continue
                                    ae = getattr(acc,cc)
                                    if not hasattr(ae,e):
                                        continue
                                    elif getattr(ae,e)!=p:
                                        print('%s.%s.%s.%s = %s'%(a,c,cc,e,p))
                                        setattr(ae,e,p)                                        
                            elif getattr(acc,cc)!=vvv:
                                print('%s.%s.%s = %s'%(a,c,cc,vvv))
                                setattr(acc,cc,vvv)
                                
                    elif getattr(ac,c)!=vv:
                        print('%s.%s = %s'%(a,c,vv))
                        setattr(ac,c,vv)
                except:
                    print('%s/%s.%s=%s failed!'%(device,a,c,vv))
                    traceback.print_exc()
                    
            dp.set_attribute_config(ac)
            
    for a,v in attrs.items():
        if a.lower() in alist:
            p = v.get('polling')
            if p is not None:
                try:
                    print('%s.poll_attribute(%s,%s)'%(name,a,p))
                    if not p:
                        dp.stop_poll_attribute(a)
                    else:
                        dp.poll_attribute(a,p)
                except:
                    traceback.print_exc()
            
    return           
                    
    
    
