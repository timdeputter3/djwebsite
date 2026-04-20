import os

from flask import Flask, render_template, request, redirect

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/djs')
def djs():
    return render_template('djs.html')

@app.route('/book', methods=['GET', 'POST'])
def book():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        dj = request.form['dj']

        # Hier kan je later opslaan in database of mail sturen
        print(name, email, dj)

        return redirect('/')

    return render_template('booking.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
