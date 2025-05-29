import time
import board
import synthio
import analogio
from digitalio import DigitalInOut, Direction, Pull #  Something like this is needed for  the button read
import audiomixer
import audiobusio # for I2S audio with external I2S DAC board (Pimaroni Pico Shield)
import ulab.numpy as np # Going to use these NP arrays for storing wave shapes.


# Write Selector Assignment
write_pin = DigitalInOut(board.GP0)
write_pin.direction = Direction.INPUT # Readable pin
write_pin.pull = Pull.UP  # Defult Pull High

# Long Sonification Selector
longSon_pin = DigitalInOut(board.GP1)
longSon_pin.direction = Direction.INPUT # Readable pin
longSon_pin.pull = Pull.UP  # Defult Pull High

# Led Assignments for Logging Tasks
led = DigitalInOut(board.LED)
led.switch_to_output()

# Analog Data in
aLogIn = analogio.AnalogIn(board.GP27) #Set the analog in pin for the sensor read

button = DigitalInOut(board.GP13)
button.direction = Direction.INPUT
button.pull = Pull.DOWN

prev_state = button.value # Button state management for our debounce

# Setiing up audio object w/ GPIOS
audio = audiobusio.I2SOut(board.GP10, board.GP11, board.GP9) #define the I2S audio bus inputs/outputs


# Define Amplitude Envelopes
amp_env = synthio.Envelope(attack_time=0.2,sustain_level=1.0,release_time=0.8)
mixer = audiomixer.Mixer(channel_count=2, sample_rate=48000, buffer_size=4096)
synth = synthio.Synthesizer(channel_count=2, sample_rate=48000)

# Mixer Paramaters
audio.play(mixer)
mixer.voice[0].play(synth) # So we're essentially always playing but retriggering the envelope to make the sounds
mixer.voice[0].level = 1 # .125 # volume control really
synth.envelope = amp_env # Set the amplitude envelope globally. It's called on the ntoe anyway so doen't need to be updated in the while

# Note numbers for MIDI
root = 55
third = 59
fifth = 62

# Filter Paramaters
cornerFreq = 4000
resonance = 0.5
low_pass = synth.low_pass_filter(cornerFreq,resonance)

# create sine and falling saw
SAMPLE_SIZE = 512 # was originaly 512 then went 2048 which makes no sense. This needs to be big enough to account for all of our harmonics. Needs double our harmonics + 1 in fact
SAMPLE_VOLUME = 32767  # 0-32767  # This is 16-bit signed -32k to +32k
wave_sine = np.array(np.sin(np.linspace(0, 2*np.pi, SAMPLE_SIZE, endpoint=False)) * SAMPLE_VOLUME,
                     dtype=np.int16)
wave_saw = np.linspace(SAMPLE_VOLUME, -SAMPLE_VOLUME, num=SAMPLE_SIZE, dtype=np.int16)



# Managing bit depths and setting up the fundamental.
f = 2
fMax=17
addSaw = np.array(np.sin(np.linspace(0, 2*np.pi, SAMPLE_SIZE, endpoint=False)) * SAMPLE_VOLUME/(fMax), dtype=np.int16) #Define our fundamental


while f <= fMax-1:
    sawPartials = np.array(np.sin(np.linspace(0, f*2*np.pi, SAMPLE_SIZE, endpoint=False)) * SAMPLE_VOLUME/(fMax), dtype=np.int16) #Define our partials
    f+=1
    i=0
    while i <= len(addSaw)-1: # Add our partials
        addSaw[i] = addSaw[i] + sawPartials[i]
        print(i,f,addSaw[i])
        i+=1

def lerp(a, b, t):  # function to morph shapes w linear interpolation
    return (1-t) * a + t * b

wave_empty = np.zeros(SAMPLE_SIZE, dtype=np.int16)  # empty buffer of samples size X that we use array slice copy "[:]" on to laod in waveforms

kParam = 0 # Critically inportant. Pos is the K paramater for oru linera interpolation. The control fo rthe belnd essentially.
my_wave = wave_empty

pFlag = False # Flags when the synths is ]ed to avvoid pressing it multiple times


## This is our selection logic. If pi is setup to read and sonify in boot.py then write_pin is high. If it's low, then we log and write data
if not write_pin.value: #if low/false then
    print("Running the Logger",write_pin.value)
    try:
        with open("/data.txt", "a") as datalog:
            while True:
                data = aLogIn.value/65535
                print(write_pin.value,"Logging", data)
                datalog.write('{0:f}\n'.format(data))
                datalog.flush()
                led.value = not led.value
                time.sleep(1)
    except OSError as e:  # Typically when the filesystem isn't writeable...
        delay = 0.5  # ...blink the LED every half second.
        if e.args[0] == 28:  # If the filesystem is full...
            delay = 0.25  # ...blink the LED faster!
        while True:
            led.value = not led.value
            time.sleep(delay)

elif not longSon_pin.value:  # If the second pin is grounded then  do the longer historical sonification.
  # Logic for Historical Sonification.
  # CirciutPython readlines() overview here: https://learn.adafruit.com/micropython-hardware-sd-cards/circuitpython
  # Data is read in. Sound synth is active. Just need to pass each line from lines as a piece of data to the synth.
  # One button press should play one single historical data point?
    print("Running in Hisotrical Sonification Mode (because longSon_pin value is",longSon_pin.value,")")

    try:
        with open("/data.txt", "r") as f:
            lines = f.readlines()
            print("Reading data from file:")
            #Button Logic
            while True: #Loop works as listener for button press.
                cur_state = button.value
                if cur_state != prev_state:
                    if not cur_state:
                        for line in lines:
                            print(line)
                            kParam = float(line)
                            dataScaled = int(float(line)*12) # Read in sensor data. Map it in an integer range of 0-10 add it to midi note 'bases'. Covnert midi pitch numbers to frequency
                            dataNote1 = synthio.Note(synthio.midi_to_hz(root  + 12 - dataScaled), waveform = my_wave, filter = low_pass, amplitude = 1) # Can attach LFOs to amp;itude also
                            dataNote2 = synthio.Note(synthio.midi_to_hz(third + 12 - dataScaled), waveform = my_wave, filter = low_pass, amplitude = .5)
                            dataNote3 = synthio.Note(synthio.midi_to_hz(fifth + 12 - dataScaled), waveform = my_wave, filter = low_pass, amplitude = .75)

                            #Perform actual WaveTable morph for the Synthesis This also perforems the sonification as we ar mapping to WaveTable Position
                            my_wave[:] = lerp(wave_saw, wave_sine, kParam)
                           # synth.envelope = amp_env

                            synth.press((dataNote1, dataNote2, dataNote3)) #Press notes
                            time.sleep(.125)                                # Minimal Hold on Notes
                            synth.release_all() # Release Notes # release_all is needed because we are not tracking the eact notes we've changed to
                            time.sleep(1)
                    prev_state = cur_state

    except OSError as k:  # Typically when the filesystem isn't writeable...
        delay = 0.5  # ...blink the LED every half second.
        if k.args[0] == 28:  # If the filesystem is full...
            delay = 0.25  # ...blink the LED faster!
        while True:
            led.value = not led.value
            time.sleep(delay)
    try:
        with open("/data.txt", "a") as datalog:
            while True:
                data = aLogIn.value/65535
                print(write_pin.value,"Logging", data)
                datalog.write('{0:f}\n'.format(data))
                datalog.flush()
                led.value = not led.value
                time.sleep(1)
    except OSError as e:  # Typically when the filesystem isn't writeable...
        delay = 0.5  # ...blink the LED every half second.
        if e.args[0] == 28:  # If the filesystem is full...
            delay = 0.25  # ...blink the LED faster!
        while True:
            led.value = not led.value
            time.sleep(delay)

else:
    print("Running in Live Sonification Mode")

    while True:
        cur_state = button.value
       # print(DigitalInOut(board.GP0).value)

        if cur_state != prev_state:
            if not cur_state:
               # synth.release((dataNote1, dataNote2, dataNote3))  # release the notes we pressed but because the notes change we can't targt them with these variables
                synth.release_all() # Needed because we are not tracking the eact notes we've changed to
                pFlag = False
                print("Button is Up", "pFlag is False", "Notes are Off")
              #  print(cur_state,prev_state)

            else:
                while button.value:
                    #  print("Button is Down")
                    dataK = aLogIn.value/65535
                     #   print(pos)
                    kParam = dataK #Wavetable position is mapped directly to the data
                    dataScaled = int(12*(aLogIn.value/65535)) # Read in sensor data. Map it in an integer range of 0-10 add it to midi note 'bases'. Covnert midi pitch numbers to frequency
                    dataNote1 = synthio.Note(synthio.midi_to_hz(root  +12 -dataScaled), waveform = my_wave, panning =   0, filter = low_pass, waveform_loop_start = 0, waveform_loop_end = synthio.waveform_max_length, amplitude = 1) # Can attach LFOs to amp;itude also
                    dataNote2 = synthio.Note(synthio.midi_to_hz(third +12 -dataScaled), waveform = my_wave, panning = -.5, filter = low_pass, waveform_loop_start = 0, waveform_loop_end = synthio.waveform_max_length, amplitude = 1)
                    dataNote3 = synthio.Note(synthio.midi_to_hz(fifth +12 -dataScaled), waveform = my_wave, panning =  .5, filter = low_pass, waveform_loop_start = 0, waveform_loop_end = synthio.waveform_max_length, amplitude = 1)

                    #Perform actual WaveTable morph for the Synthesis This also perforems the sonification as we ar mapping to WaveTable Position
                    my_wave[:] = lerp(addSaw, wave_sine, kParam)
                   #synth.envelope = amp_env


                    # Play the Chord assuming the pFlag is false
                    if not pFlag:
                        synth.press((dataNote1, dataNote2, dataNote3))  # press down chords consisting of data mapped to midi numbers converted to pitch
                        pFlag = True
                        print("Button is Down", "pFlag is True", "Notes are On", "Data_2_Table: ", dataK)

        prev_state = cur_state