#!/usr/bin/python -u

import sys
#from gi.repository import GObject
import gobject
import dbus
import dbus.service
import dbus.mainloop.glib
import os
import Openbmc

## Abstract class, must subclass
class SensorValue(Openbmc.DbusProperties):
	IFACE_NAME = 'org.openbmc.SensorValue'
	def __init__(self,bus,name):
		#Openbmc.DbusProperties.__init__(self)
		self.Set(SensorValue.IFACE_NAME,'units',"")
		self.Set(SensorValue.IFACE_NAME,'error',False)
		
	@dbus.service.method(IFACE_NAME,
		in_signature='v', out_signature='')
	def setValue(self,value):
		self.Set(SensorValue.IFACE_NAME,'value',value)

	@dbus.service.method(IFACE_NAME,
		in_signature='', out_signature='v')
	def getValue(self):
		return self.Get(SensorValue.IFACE_NAME,'value')

class SensorThresholds(Openbmc.DbusProperties):
	IFACE_NAME = 'org.openbmc.SensorThresholds'
	def __init__(self,bus,name):
		self.Set(SensorThresholds.IFACE_NAME,'thresholds_enabled',False)
		self.Set(SensorThresholds.IFACE_NAME,'warning_upper',0)
		self.Set(SensorThresholds.IFACE_NAME,'warning_lower',0)
		self.Set(SensorThresholds.IFACE_NAME,'critical_upper',0)
		self.Set(SensorThresholds.IFACE_NAME,'critical_lower',0)
		self.Set(SensorThresholds.IFACE_NAME,'critical_lower',0)
		self.Set(SensorThresholds.IFACE_NAME,'threshold_state',"NORMAL")
		self.Set(SensorThresholds.IFACE_NAME,'worst_threshold_state',"NORMAL")
	
	@dbus.service.method(IFACE_NAME,
		in_signature='', out_signature='')
	def resetThresholdState(self):
		self.Set(SensorThresholds.IFACE_NAME,'worst_threshold_state',"NORMAL")

	def check_thresholds(self,value):
		iface = SensorThresholds.IFACE_NAME
		if (self.Get(iface,'thresholds_enabled') == False):
			return False
		rtn = False
		current_state = "NORMAL"
		if (value >= self.properties[iface]['critical_upper']):
			current_state = "CRITICAL"
			rtn = True	
		elif (value <= self.properties[iface]['critical_lower']):
			current_state = "CRITICAL"	
			rtn = True	
		elif (value >= self.properties[iface]['warning_upper']):
			current_state = "WARNING"	
			rtn = True	
		elif (value <= self.properties[iface]['warning_lower']):
			current_state = "WARNING"	
			rtn = True
		self.Set(iface,'threshold_state',current_state)
		worst = self.properties[iface]['worst_threshold_state']
		if (current_state == "CRITICAL" or 
		   (current_state == "WARNING" and worst != "CRITICAL")):
			self.Set(iface,'worst_threshold_state',current_state)

		return rtn

class VirtualSensor(SensorValue):
	def __init__(self,bus,name):
		Openbmc.DbusProperties.__init__(self)
		SensorValue.__init__(self,bus,name)
		dbus.service.Object.__init__(self,bus,name)

class HwmonSensor(SensorValue,SensorThresholds):
	IFACE_NAME = 'org.openbmc.HwmonSensor'
	def __init__(self,bus,name):
		Openbmc.DbusProperties.__init__(self)
		SensorValue.__init__(self,bus,name)
		SensorThresholds.__init__(self,bus,name)
		self.Set(HwmonSensor.IFACE_NAME,'scale',1)
		self.Set(HwmonSensor.IFACE_NAME,'offset',0)
		self.Set(HwmonSensor.IFACE_NAME,'filename','')
		self.value_dirty = False

		# need to cache value to know if changed
		self.value = None
		dbus.service.Object.__init__(self,bus,name)

	@dbus.service.method(SensorValue.IFACE_NAME,
		in_signature='v', out_signature='')
	def setValue(self,value):
		self.value_dirty = True
		SensorValue.setValue(self,value)

	## Called by sensor process to update value from polling
	## if returns not None, then sensor process will update hwmon value
	@dbus.service.method(IFACE_NAME,
		in_signature='v', out_signature='(bv)')
	def setByPoll(self,value):
		scale = self.properties[HwmonSensor.IFACE_NAME]['scale']
		offset = self.properties[HwmonSensor.IFACE_NAME]['offset']
		if (self.value_dirty == True):
			## new value externally set, so just return to hwmon
			## process to write value
			self.value_dirty = False
			val = (self.properties[SensorValue.IFACE_NAME]['value']-offset) * scale
			return [True,val]
		else:
			val = (value/scale) + offset
			if (val != self.value):
				SensorValue.setValue(self,val)
				self.check_thresholds(val)
				self.value = val

			return [False,0]
		
CONTROL_IFACE = 'org.openbmc.Control'
class PowerCap(VirtualSensor):
	def __init__(self,bus,name):
		VirtualSensor.__init__(self,bus,name)
		self.setValue(100)

		
class BootProgressSensor(VirtualSensor):
	def __init__(self,bus,name):
		VirtualSensor.__init__(self,bus,name)
		self.setValue("Off")
		bus.add_signal_receiver(self.SystemStateHandler,signal_name = "GotoSystemState")

	def SystemStateHandler(self,state):
		if (state == "HOST_POWERED_OFF"):
			self.setValue("Off")


	##override setValue method
	@dbus.service.method(SensorValue.IFACE_NAME,
		in_signature='v', out_signature='')
	def setValue(self,value):
		SensorValue.setValue(self,value)
		if (value == "FW Progress, Starting OS"):
			self.GotoSystemState("HOST_BOOTED")
			
	@dbus.service.signal(CONTROL_IFACE,signature='s')
	def GotoSystemState(self,state):
		pass
		
class OccStatusSensor(VirtualSensor):
	def __init__(self,bus,name):
		VirtualSensor.__init__(self,bus,name)
		self.setValue("Disabled")
		bus.add_signal_receiver(self.SystemStateHandler,signal_name = "GotoSystemState")

	def SystemStateHandler(self,state):
		if (state == "HOST_POWERED_OFF"):
			self.setValue("Disabled")
			

	##override setValue method
	@dbus.service.method(SensorValue.IFACE_NAME,
		in_signature='v', out_signature='')
	def setValue(self,value):
		if (value == "Enabled"):
			print "Installing OCC device"
			os.system("echo occ-i2c 0x50 >  /sys/bus/i2c/devices/i2c-3/new_device")
			os.system("echo occ-i2c 0x51 >  /sys/bus/i2c/devices/i2c-3/new_device")
		else:
			print "Deleting OCC device"
			os.system("echo 0x50 >  /sys/bus/i2c/devices/i2c-3/delete_device")
			os.system("echo 0x51 >  /sys/bus/i2c/devices/i2c-3/delete_device")


		SensorValue.setValue(self,value)
			
	@dbus.service.signal(CONTROL_IFACE,signature='s')
	def GotoSystemState(self,state):
		pass
	
class BootCountSensor(VirtualSensor):
	def __init__(self,bus,name):
		VirtualSensor.__init__(self,bus,name)
		self.setValue(2)

class OperatingSystemStatusSensor(VirtualSensor):
	def __init__(self,bus,name):
		VirtualSensor.__init__(self,bus,name)
		self.setValue("Off")
	

