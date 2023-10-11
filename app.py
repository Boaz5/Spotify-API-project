from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import mysql.connector
from time import time

load_dotenv()

app = Flask(__name__)

app.secret_key = "key"
app.config['SESSION_COOKIE_NAME']= 'Spotify Project'
TOKEN_INFO = "token_info"


#access and use sql to store my database of songs
db = mysql.connector.connect(
    host="localhost",
    user="root",
    passwd=os.getenv("SQL_PASSWORD"),
    database="spotifyDataBase"
)
mycursor = db.cursor()

@app.route('/')
def login():
    auth_url = create_spotify_oauth().get_authorize_url()
    return redirect(auth_url)

@app.route('/redirect')
def redirectPage():
    session.clear()
    code = request.args.get('code')
    sp_oauth = create_spotify_oauth()
    token_info = sp_oauth.get_access_token(code) #exchanges the oauth code for a access token
    session[TOKEN_INFO] = token_info
    return redirect(url_for('homepage', _external=True))

@app.route('/home', methods = ["POST" , "GET"])
def homepage():
    if request.method == "POST":
        if request.form.get("choice")=="store":
            return redirect(url_for('tracking', _external=True))
        elif request.form.get("choice")=="create":
            return redirect(url_for('create', _external=True))
    else:
        return render_template("index.html")
    
@app.route('/track')
def tracking():
    try:
        token_info = get_token()
    except:
        print("User not logged in")
        return redirect('/')
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    user = check_user(sp.current_user())
    mycursor.execute("SELECT last_song FROM users WHERE user_id=%s", (user["id"], ))
    last_played_song = mycursor.fetchone()[0]
    mycursor.execute("SELECT timestamp FROM users WHERE user_id=%s", (user["id"], ))
    last_played_song_timestamp = mycursor.fetchone()[0]

    try:
        if (sp.current_user_playing_track()):
            if last_played_song=="None":
                mycursor.execute("UPDATE users SET last_song=%s, timestamp=%s WHERE user_id=%s", (sp.current_user_playing_track()['item']['name'],sp.current_user_playing_track()['timestamp'], user['id']))
                db.commit()
                mycursor.execute("SELECT last_song FROM users WHERE user_id=%s", (user["id"], ))
                last_played_song = mycursor.fetchone()[0]
                print(last_played_song)
            else: #using current_user_recently_played I can maybe track the songs I skipped
                current_song = sp.current_user_playing_track()
                if current_song['item']['name']!=last_played_song:
                    recently_played=sp.current_user_recently_played(limit=50, after=last_played_song_timestamp)
                    for recent_song in recently_played['items']:
                        print(recent_song['track']['name'])
                        data = store_data(user, recent_song['track']['name'])#track the 50 recently played and find the song from there that was the last current song and all song in between is considered skipped
                #add data into sql database
                    mycursor.execute("UPDATE users SET last_song=%s, timestamp=%s WHERE user_id=%s", (current_song['item']['name'],current_song['timestamp'], user['id']))
                    db.commit() #swapped the last current song to this current song
                    print("stored")
                else:
                    print("You are currently playing the same song")
    except:
        print("Need a Song to Currently Play To Track")
    return "Tracked <a href='/home'>Return to HomePage</a>"

@app.route('/create', methods=["POST", "GET"])
def create():
    try:
        token_info=get_token()
    except:
        print("User Not Logged In")
        return redirect("/")
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    playlists = sp.current_user_playlists()['items']
    user = check_user(sp.current_user())
    
    if request.method=="POST":
        
        playlist_chosen = request.form.get("playlist_chosen")
        new_playlist_name = request.form.get("playlist_name")
        mycursor.execute("SELECT song FROM datas WHERE user_id=%s", (user['id'], ))
        songs = mycursor.fetchall()
        
        #create the playlist and then grab it's id
        sp.user_playlist_create(user['id'],new_playlist_name, True, False, "Created By The Bobo Tracker")
        updated_playlists = sp.current_user_playlists()['items']
        new_playlist_id = ""
        for playlist in updated_playlists:
            if playlist['name'] == new_playlist_name:
                new_playlist_id = playlist['id']
                break
        
        all_songs_items = []
        all_songs_name = []
        all_songs_uri = []
        songs_in_data = []
        uri_not_in_data = []
        iteration = 0
        
        for song in songs:
            songs_in_data.append(song[0])
#stores all the songs' items detail into a list
        while True:
            items = sp.playlist_tracks(playlist_chosen, limit=100, offset=iteration*100)["items"]
            iteration +=1
            all_songs_items +=items
            if(len(items)<100):
                break

#stores only the names and song uri into a dictionary
        for item in all_songs_items:
            all_songs_name.append(item['track']['name'])
            all_songs_uri.append(item['track']['uri'])
        print(new_playlist_id)
        for i in range(0, len(all_songs_name)):
            if all_songs_name[i] not in songs_in_data:
                uri_not_in_data.append(all_songs_uri[i])
            if i%100==0:
                sp.user_playlist_add_tracks(user['id'], new_playlist_id, uri_not_in_data, None)
                uri_not_in_data.clear()
        sp.user_playlist_add_tracks(user['id'], new_playlist_id, uri_not_in_data, None)
            
        return "Created <a href='/home'>Return to HomePage</a>"
    else:
        return render_template("create.html", playlists=playlists)


def get_token():
    token_info=session.get(TOKEN_INFO, None)
    if not token_info:
        return redirect(url_for('login', _external=False)) # redirect to the login if no token
        
    now = int(time.time())
    
    expired = token_info['expires_at'] - now < 60 #token has information to when it expires so we check within 60 sec
    if (expired):
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
    return token_info


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("CLIENT_ID"),
        client_secret= os.getenv("CLIENT_SECRET"),
        redirect_uri=url_for('redirectPage', _external=True),
        scope='user-library-read user-read-currently-playing playlist-modify-public playlist-modify-private user-read-playback-state user-read-recently-played user-read-private playlist-read-private'
        )

#will confirm whether the user is already in the database or not
def check_user(user):
    #ensure that I fetch or iterate through the result set (if any) before closing the cursor. 
    mycursor.execute("SELECT * FROM users WHERE user_id= %s ", (user['id'], ))
    result = mycursor.fetchone()
    if result:
        mycursor.execute("SELECT COUNT(song) FROM datas WHERE user_id = %s", (user['id'], ))
        count = mycursor.fetchone()[0]
        mycursor.execute("UPDATE users SET songs_in_database = %s WHERE user_id = %s", (count, user['id']))
        db.commit()
        return user
    else:
        mycursor.execute("INSERT INTO users (user_id, name, songs_in_database) VALUES (%s,%s,%s)", (user['id'], user['display_name'], 0))
        db.commit()
        return user

def store_data(user, song):#we know user is in the database
    mycursor.execute("SELECT count FROM datas WHERE user_id=%s AND song=%s", (user['id'], song ))
    result = mycursor.fetchone()
    if result:
        count = result[0] + 1
        mycursor.execute("UPDATE datas SET count = %s WHERE user_id = %s AND song = %s", (count, user['id'], song))
        db.commit()
    else:#user is not in the database
        mycursor.execute("INSERT INTO datas (user_id, display_name, song, count) VALUES (%s, %s, %s, %s)", (user['id'], user['display_name'], song, 1))
        db.commit()
        mycursor.execute("SELECT count FROM datas WHERE user_id = %s AND song = %s", (user['id'], song))
        count = mycursor.fetchone()[0]
    return (f"{song} is stored and the count is currently {count}")


def sort_playlist():
    pass

if __name__ == "__main__":
    app.run(debug=True)
