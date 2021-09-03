#!/usr/bin/env python3
import datetime, re, tzlocal, json, os, PIL, sys, argparse
from noaa_sdk import NOAA
from PIL import Image, ImageDraw, ImageFont
import epd4in01f

def type_hours(string):
    val = int(string)
    if val < 0 or val > 23:
        raise Exception('Value must be an integer between 0 and 23')
    return val

parser = argparse.ArgumentParser()
parser.add_argument('--test', action='store_true', help='Output test image (to test.png)')
parser.add_argument('--no-epaper', action='store_true', help='Do *not* output to the e-paper display')
parser.add_argument('--current-time', type=type_hours, default=None, help='Set the current time to be a spoofed value at (begin) + this many hours')
parser.add_argument('--debug-output', action='store_true', help='Output debug messages')
args = parser.parse_args()

def printd(*pargs, **kwargs):
    if args.debug_output:
        print(*pargs, **kwargs)

font_title = ImageFont.truetype('Inconsolata.otf', 24)
font_labels = ImageFont.truetype('RictyDiminished-Bold.ttf', 14)

weather_zip = '27529'
weather_country = 'US'
localTz = tzlocal.get_localzone()
localNow = datetime.datetime.now(localTz)
measureStart = localNow.replace(hour=int(localNow.hour/12)*12, minute=0, second=0, microsecond=0)
weather_cachefile = localNow.strftime('weather_cache.json')
# Add some extra time to the forecast so we can have a nice end to the graph
oneDayHence = measureStart + datetime.timedelta(days=1, hours=1)
isoPat = re.compile(r'(?P<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?P<timezone>[\+-][0-9]{2}:[0-9]{2})(/P.+)?')

white = (255,255,255)
black = (0,0,0)
red = (255,0,0)
green = (0,255,0)
blue = (0,0,255)
yellow = (255,255,0)

def getLinePoints(values, timeToXFunc, yScaleFactor=None, minValue=None, yAdd=None):
    if yScaleFactor is None:
        yScaleFactor = 1
    if yAdd is None:
        yAdd = 0
    if minValue is None:
        minValue = 0
    points = []
    for value in values:
        points.append(
                (timeToXFunc(value['time']),
                yAdd+(value['value']-minValue)*yScaleFactor,
                value['value'])
            )
    return points

def extractValues(timeAndValueDict):
    return [val['value'] for val in timeAndValueDict]

def drawGraph(date, curTime, whenUpdated, location, graphData):
    imageArea = (640,400)
    img = Image.new('RGB', imageArea, (255,255,255))
    draw = ImageDraw.Draw(img)
    exteriorImagePadding = (38, 20)
    graphPadding = (5,5)
    majorDivisions = 4
    tempFmtLabel = '{:.0f}°F'
    pctLabel = '{:.0f}%'
    currentTimeWidth = 20
    legendSquareSize = (10,10)
    bumpOffset = 2

    def timeLabel(inTime):
        hLabel = ''
        if inTime.hour == 12:
            hLabel = 'Noon'
        elif inTime.hour == 0 or inTime.hour == 24:
            hLabel = 'Midnight'
        else:
            hLabel = '{:d} {:s}'.format(int(inTime.strftime('%I')), inTime.strftime('%p'))
        if date.date() != inTime.date():
            return '{:s} {:s}'.format(inTime.strftime('%a'), hLabel)
        else:
            return hLabel

    # We add some external padding so that the edges of the screen don't get hard to read (and to accomodate some legends on the graph)
    titleArea = ((exteriorImagePadding[0], imageArea[0]-exteriorImagePadding[0]), (exteriorImagePadding[1], 100))
    graphArea = ((exteriorImagePadding[0], imageArea[0]-exteriorImagePadding[0]), (120, imageArea[1]-exteriorImagePadding[1]))

    titleSize = (titleArea[0][1]-titleArea[0][0], titleArea[1][1]-titleArea[1][0])
    # We make the graph slightly smaller than the outline area, 5 px padding on all sides
    graphSize = (graphArea[0][1] - graphArea[0][0] - (graphPadding[0]*2), graphArea[1][1] - graphArea[1][0] - (graphPadding[1]*2))

    beginTime = graphData[0]['time']
    endTime = graphData[-1]['time']
    roundBegin = beginTime.replace(minute=0 if beginTime.minute < 30 else 30, second=0, microsecond=0)
    roundEnd = endTime.replace(hour=endTime.hour+1 if endTime.minute>=30 else endTime.hour, minute=30 if endTime.minute < 30 else 0, second=0, microsecond=0)
    timeRange = roundEnd - roundBegin
    hoursDisplayed = int(timeRange / datetime.timedelta(hours=1))
    baseDate = date.replace(hour=int(roundBegin.hour/3)*3, minute=0, second=0, microsecond=0)

    if args.current_time is not None:
        curTime = beginTime.replace(hour=beginTime.hour+args.current_time)
    
    temperatures = [{'time':val['time'], 'value':val['temperature']} for val in graphData]
    chancePrecips = [{'time':val['time'], 'value':val['probabilityOfPrecipitation']} for val in graphData]
    humidities = [{'time':val['time'], 'value':val['relativeHumidity']} for val in graphData]

    def timeToGraphX(inTime):
        return graphArea[0][0]+graphPadding[0]+((inTime - roundBegin)/timeRange)*graphSize[0]
    
    tempExtents = (min(50, min([val['value'] for val in temperatures])-10), max(60, max([val['value'] for val in temperatures])+10))

    measurePoints = max(len(chancePrecips), len(temperatures), len(humidities))
    pointIncrease = graphSize[0] / float(measurePoints)
    quarterIncrease = graphSize[0]/float(majorDivisions)
    hourIncrease = graphSize[0]/float(hoursDisplayed)

    degreeScale = float(graphSize[1])/-(tempExtents[1]-tempExtents[0])
    percentScale = float(graphSize[1])/-100

    # Title
    titleLabel = 'Weather for {}'.format(location)
    titleLabelSize = font_title.getsize(titleLabel)
    draw.text((titleArea[0][0], titleArea[1][0]), titleLabel, font=font_title, fill=black)
    # Date
    dateLabel = date.strftime('%A %b %d %Y')
    dateLabelSize = font_title.getsize(dateLabel)
    draw.text( (titleArea[0][0], titleArea[1][0]+titleLabelSize[1]+bumpOffset), dateLabel, font=font_title, fill=black)
    # Updated/Updated
    retrLabel = 'Data Updated {}'.format(whenUpdated.strftime('%Y-%m-%d %H:%M:%S'))
    nowLabel = 'Graph Updated {}'.format(curTime.strftime('%H:%M:%S'))
    retrLabelSize = font_labels.getsize(retrLabel)
    nowLabelSize = font_labels.getsize(nowLabel)
    # Legend
    precipLabel = 'Precip. Chance'
    tempLabel = 'Temperature'
    humidLabel = 'Rel. Humidity'
    curTimeLabel = 'Current Time'
    precipLabelSize = font_labels.getsize(precipLabel)
    tempLabelSize = font_labels.getsize(tempLabel)
    humidLabelSize = font_labels.getsize(humidLabel)
    curTimeLabelSize = font_labels.getsize(curTimeLabel)


    # Now that we have the full legend's size, actually draw it all
    lineHeights = [0]
    lineHeights.append(lineHeights[-1]+retrLabelSize[1]+bumpOffset)
    lineHeights.append(lineHeights[-1]+nowLabelSize[1]+bumpOffset)
    lineHeights.append(lineHeights[-1]+precipLabelSize[1]+bumpOffset)

    maxX1 = max(retrLabelSize[0], nowLabelSize[0])
    maxX2 = max(precipLabelSize[0]+legendSquareSize[0]+bumpOffset, tempLabelSize[0]+legendSquareSize[0]+bumpOffset,
                humidLabelSize[0]+legendSquareSize[0]+bumpOffset,  curTimeLabelSize[0]+legendSquareSize[0]+bumpOffset)
    lineStarts = [max(maxX1, (maxX2+bumpOffset)*2), maxX2]

    legendBase = (titleArea[0][1]-lineStarts[0], titleArea[1][0], titleArea[0][1]-lineStarts[1])

    draw.text( (legendBase[0], legendBase[1]+lineHeights[0]), retrLabel, font=font_labels, fill=black)
    draw.text( (legendBase[0], legendBase[1]+lineHeights[1]), nowLabel, font=font_labels, fill=black)
    # The legend labels also need their colors
    draw.rectangle( ((legendBase[0], legendBase[1]+lineHeights[2]), (legendBase[0]+legendSquareSize[0], legendBase[1]+lineHeights[2]+legendSquareSize[1])), fill=blue)
    draw.rectangle( ((legendBase[0], legendBase[1]+lineHeights[3]), (legendBase[0]+legendSquareSize[0], legendBase[1]+lineHeights[3]+legendSquareSize[1])), fill=red)
    draw.rectangle( ((legendBase[2], legendBase[1]+lineHeights[2]), (legendBase[2]+legendSquareSize[0], legendBase[1]+lineHeights[2]+legendSquareSize[1])), fill=green)
    draw.rectangle( ((legendBase[2], legendBase[1]+lineHeights[3]), (legendBase[2]+legendSquareSize[0], legendBase[1]+lineHeights[3]+legendSquareSize[1])), fill=yellow)
    draw.text( (legendBase[0]+legendSquareSize[0]+bumpOffset, legendBase[1]+lineHeights[2]), precipLabel, font=font_labels, fill=black)
    draw.text( (legendBase[0]+legendSquareSize[0]+bumpOffset, legendBase[1]+lineHeights[3]), tempLabel, font=font_labels, fill=black)
    draw.text( (legendBase[2]+legendSquareSize[0]+bumpOffset, legendBase[1]+lineHeights[2]), humidLabel, font=font_labels, fill=black)
    draw.text( (legendBase[2]+legendSquareSize[0]+bumpOffset, legendBase[1]+lineHeights[3]), curTimeLabel, font=font_labels, fill=black)

    

    # outlining the graph area
    draw.line( ( (graphArea[0][0], graphArea[1][0]), (graphArea[0][1], graphArea[1][0]), (graphArea[0][1], graphArea[1][1]),
                 (graphArea[0][0], graphArea[1][1]), (graphArea[0][0], graphArea[1][0]) ), fill=black, width=2)

    # adding the current time marker
    currTimeMark = graphArea[0][0]+graphPadding[0]+((curTime - roundBegin)/timeRange)*graphSize[0]
    minXes = ( max(graphArea[0][0]+graphPadding[0], currTimeMark-(currentTimeWidth/2.0)), min(graphArea[0][1]-graphPadding[0], currTimeMark+(currentTimeWidth/2.0)) )
    draw.rectangle( ((minXes[0], graphArea[1][0]+graphPadding[1]), (minXes[1], graphArea[1][1]-graphPadding[1])), fill=yellow)

    # adding the quarter-day marks
    quarterTimes = [baseDate + datetime.timedelta(hours=6)*i for i in range(5)]
    quarterMarks = [(timeToGraphX(tim), tim) for tim in quarterTimes]
    for mark in quarterMarks:
        draw.line( ((mark[0], graphArea[1][0]+graphPadding[1]), (mark[0], graphArea[1][1]-graphPadding[1])), fill=black, width=1)

    # adding the hourly marks
    hourTimes = [roundBegin.replace(hour=roundBegin.hour+1 if roundBegin.minute>0 else roundBegin.hour, minute=0) +datetime.timedelta(hours=1)*i for i in range(hoursDisplayed)]
    hourMarks = [(timeToGraphX(tim), tim) for tim in hourTimes]
    for mark in hourMarks:
        draw.line( ((mark[0], graphArea[1][0]+graphPadding[1]), (mark[0], graphArea[1][0]+graphPadding[1]+graphSize[1]/10)), fill=black, width=1)
    
    # Temp scale
    highLabel =  tempFmtLabel.format(tempExtents[1])
    lowLabel = tempFmtLabel.format(tempExtents[0])
    highSize = font_labels.getsize(highLabel)
    lowSize = font_labels.getsize(lowLabel)
    draw.text( (graphArea[0][0]-lowSize[0]-3, graphArea[1][1]-lowSize[1]), lowLabel, fill=black, font=font_labels)
    draw.text( (graphArea[0][0]-highSize[0]-3, graphArea[1][0]), highLabel, fill=black, font=font_labels)
    # Percentage scale
    highLabel = pctLabel.format(100)
    lowLabel = pctLabel.format(0)
    highSize = font_labels.getsize(highLabel)
    lowSize = font_labels.getsize(lowLabel)
    draw.text( (graphArea[0][1]+3, graphArea[1][1]-lowSize[1]), lowLabel, fill=black, font=font_labels)
    draw.text( (graphArea[0][1]+3, graphArea[1][0]), highLabel, fill=black, font=font_labels)

    # draw precipitation line
    precipPoints = getLinePoints(chancePrecips, timeToGraphX, yScaleFactor=percentScale, yAdd=graphArea[1][1]-graphPadding[1])
    draw.line( [(v[0], v[1]) for v in precipPoints], fill=blue, width=10, joint='curve')
    # draw temp line
    tempPoints = getLinePoints(temperatures, timeToGraphX, yScaleFactor=degreeScale, minValue=tempExtents[0], yAdd=graphArea[1][1]-graphPadding[1])
    draw.line( [(v[0], v[1]) for v in tempPoints], fill=red, width=10, joint='curve')
    # draw humidity line
    humidPoints = getLinePoints(humidities, timeToGraphX, yScaleFactor=percentScale, yAdd=graphArea[1][1]-graphPadding[1])
    draw.line( [(v[0], v[1]) for v in humidPoints], fill=green, width=10, joint='curve')

    # draw precipitation checkpoints
    precipCheckpoints = precipPoints[0::7]
    for checkpoint in precipCheckpoints:
        chkLabel = pctLabel.format(checkpoint[2])
        chkSize = font_labels.getsize(chkLabel)
        draw.text( (checkpoint[0], checkpoint[1]-chkSize[1]-3), chkLabel, fill=black, font=font_labels)
    # draw temp checkpoints
    tempCheckpoints = tempPoints[2::7]
    for checkpoint in tempCheckpoints:
        chkLabel = tempFmtLabel.format(checkpoint[2])
        chkSize = font_labels.getsize(chkLabel)
        draw.text( (checkpoint[0], checkpoint[1]-chkSize[1]-3), chkLabel, fill=black, font=font_labels)
    # draw humidity checkpoints
    humidCheckpoints = humidPoints[4::7]
    for checkpoint in humidCheckpoints:
        chkLabel = pctLabel.format(checkpoint[2])
        chkSize = font_labels.getsize(chkLabel)
        draw.text( (checkpoint[0], checkpoint[1]-chkSize[1]-3), chkLabel, fill=black, font=font_labels)
    # draw time checkpoints
    for checkpoint in quarterMarks:
        chkLabel = timeLabel(checkpoint[1])
        chkSize = font_labels.getsize(chkLabel)
        draw.text( (checkpoint[0]-(chkSize[0]/2.0), graphArea[1][0]-chkSize[1]-3), chkLabel, fill=black, font=font_labels)

    return img


def extractTimeFromDuration(inStr):
    mat = isoPat.match(inStr)
    if mat is None:
        return None
    timeStr = mat.group('timestamp')
    timeZone = mat.group('timezone').replace(':', '')
    return datetime.datetime.strptime('{}{}'.format(timeStr, timeZone), '%Y-%m-%dT%X%z').astimezone(localTz)

within24Hours = lambda time: oneDayHence >= time

def extractTimeValues(resultGroup):
    return [{'value':value['value'], 'validTime':extractTimeFromDuration(value['validTime'])}
              for value in resultGroup['values']
              if within24Hours(extractTimeFromDuration(value['validTime']))
           ]

def convertCToF(cel):
    return 1.8 * cel + 32

def coerceDatetimesToStrings(alist):
    return [{'value':value['value'], 'validTime':value['validTime'].strftime('%Y-%m-%dT%X%z')}
            for value in alist]

result = None
tooOld = False
def retrieve_weather():
    noaa = NOAA()
    return noaa.get_forecasts(weather_zip, weather_country, type='forecastGridData')

if os.path.isfile(weather_cachefile):
    printd('Loading cached weather from {}'.format(weather_cachefile))
    with open(weather_cachefile, 'r') as infil:
        result = json.load(infil)
    updateTime = extractTimeFromDuration(result['updateTime'])
    # if the data is over 24 hours old, repull it
    if updateTime+datetime.timedelta(hours=24) < datetime.datetime.now(localTz):
        printd('Cache too old (updated {}), reloading'.format(updateTime.strftime('%Y-%m-%d %H:%M:%S')))
        tooOld = True
if tooOld or result is None:
    printd('Retreiving weather and caching in {}'.format(weather_cachefile))
    result = retrieve_weather()
    with open(weather_cachefile, 'w') as outfil:
        json.dump(result, outfil)

updateTime = extractTimeFromDuration(result['updateTime'])

precip = extractTimeValues(result['probabilityOfPrecipitation'])
temp = extractTimeValues(result['temperature'])
humid = extractTimeValues(result['relativeHumidity'])

halfHourValues = []
curTime = measureStart
#print('Here\'s a dump of the lists we\'re using:')
#print(json.dumps(coerceDatetimesToStrings(precip),indent=1))
#print(json.dumps(coerceDatetimesToStrings(temp),indent=1))
#print(json.dumps(coerceDatetimesToStrings(humid),indent=1))
while curTime < oneDayHence:
    curPrecip = None
    curTemp = None
    curHumid = None
    for idx in range(0, max(len(precip), len(temp), len(humid))):
        if idx < len(precip) and (curPrecip is None or curTime >= precip[idx]['validTime']):
            curPrecip = precip[idx]['value']
        if idx < len(temp) and (curTemp is None or curTime >= temp[idx]['validTime']):
            curTemp = temp[idx]['value']
        if idx < len(humid) and (curHumid is None or curTime >= humid[idx]['validTime']):
            curHumid = humid[idx]['value']
    if curPrecip is None or curTemp is None or curHumid is None:
        printd('Crap, we weren\'t able to find any data for one of these values:\nprecipitation: {}, temperature: {}, humidity: {}'.format(curPrecip, curTemp, curHumid))
    halfHourValues.append({'time':curTime, 'probabilityOfPrecipitation':curPrecip, 'temperature':convertCToF(curTemp), 'relativeHumidity':curHumid})
    curTime += datetime.timedelta(minutes=30)

img = drawGraph(measureStart, localNow, updateTime, '{}, {}'.format(weather_zip, weather_country), halfHourValues)
if args.test:
    img.save('test.png', 'PNG')
if not args.no_epaper:
    printd('Drawing to e-paper...')
    try:
        epd = epd4in01f.EPD()
        epd.init()
        epd.Clear()
        epd.display(epd.getbuffer(img))
        epd.sleep()
    except:
        epd4in01f.epdconfig.module_exit()
    printd('Drawing complete')
